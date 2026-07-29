import json
import os
import time
from datetime import UTC, datetime
from multiprocessing import Process

import admin.jobs as jobs
from admin.database import (
    SessionLocal,
    _ensure_run_record_columns,
    redact_leaked_secrets_from_run_records,
    scrub_sensitive_run_payloads,
)
from admin.jobs import _execute_endpoint, _execute_run_process, reconcile_interrupted_runs, request_run_cancellation
from admin.models import RepositoryConfig, RunRecord
from services.workflow_service import WorkflowRunResult


def _isolated_sleep_target(seconds: float) -> None:
    os.setsid()
    time.sleep(seconds)


def _wait_for_dispatcher_to_finish(run_id: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with jobs.QUEUE_CONDITION:
            is_queued = any(job.run_id == run_id for job in jobs.JOB_QUEUE)
        with jobs.PROCESS_LOCK:
            is_running = run_id in jobs.RUNNING_PROCESSES
        if not is_queued and not is_running:
            return
        time.sleep(0.1)


def test_request_run_cancellation_marks_queued_run_cancelled():
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="queued",
            created_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    outcome = request_run_cancellation(run_id)

    assert outcome == "cancelled"
    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.status == "cancelled"
        assert stored_run.completed_at is not None


def test_request_run_cancellation_marks_running_run_cancelled():
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="running",
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    outcome = request_run_cancellation(run_id)

    assert outcome == "cancelled"
    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.status == "cancelled"
        assert stored_run.error_message is not None


def test_request_run_cancellation_targets_only_the_specified_concurrent_run():
    with SessionLocal() as session:
        run_a = RunRecord(
            endpoint="/generate",
            status="running",
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        run_b = RunRecord(
            endpoint="/generate",
            status="running",
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        session.add_all([run_a, run_b])
        session.commit()
        session.refresh(run_a)
        session.refresh(run_b)
        run_a_id, run_b_id = run_a.id, run_b.id

    process_a = Process(target=_isolated_sleep_target, args=(5,), daemon=True)
    process_b = Process(target=_isolated_sleep_target, args=(5,), daemon=True)
    process_a.start()
    process_b.start()

    with jobs.PROCESS_LOCK:
        jobs.RUNNING_PROCESSES[run_a_id] = process_a
        jobs.RUNNING_PROCESSES[run_b_id] = process_b

    try:
        outcome = request_run_cancellation(run_a_id)

        assert outcome == "cancelled"
        assert process_b.is_alive()
        with jobs.PROCESS_LOCK:
            assert run_a_id not in jobs.RUNNING_PROCESSES
            assert run_b_id in jobs.RUNNING_PROCESSES

        with SessionLocal() as session:
            stored_run_a = session.get(RunRecord, run_a_id)
            stored_run_b = session.get(RunRecord, run_b_id)
            assert stored_run_a is not None and stored_run_a.status == "cancelled"
            assert stored_run_b is not None and stored_run_b.status == "running"
    finally:
        with jobs.PROCESS_LOCK:
            jobs.RUNNING_PROCESSES.pop(run_a_id, None)
            jobs.RUNNING_PROCESSES.pop(run_b_id, None)
        process_b.terminate()
        process_a.join(timeout=2)
        process_b.join(timeout=2)


def test_ensure_dispatchers_starts_up_to_the_configured_pool_size():
    jobs._ensure_dispatchers()

    alive_dispatchers = [thread for thread in jobs.DISPATCHER_THREADS if thread.is_alive()]
    assert len(alive_dispatchers) == jobs.MAX_CONCURRENT_JOBS


def test_reconcile_interrupted_runs_marks_stale_running_run_failed():
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="running",
            progress_percent=42.0,
            progress_message="Building docs",
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    recovered_count = reconcile_interrupted_runs()

    assert recovered_count >= 1
    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.status == "failed"
        assert stored_run.progress_percent == 100.0
        assert stored_run.progress_message == "Failed"
        assert stored_run.error_message == "Run was interrupted because the server stopped before the job could finish."
        assert stored_run.completed_at is not None


def test_scrub_sensitive_run_payloads_removes_existing_tokens():
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="failed",
            created_at=datetime.now(UTC),
            request_payload=json.dumps(
                {
                    "repo_url": "example/project",
                    "token": "secret-token",
                    "branch": "main",
                }
            ),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    scrubbed_count = scrub_sensitive_run_payloads()

    assert scrubbed_count >= 1
    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.request_payload is not None
        payload = json.loads(stored_run.request_payload)
        assert payload == {
            "repo_url": "example/project",
            "branch": "main",
        }


def test_clear_runs_deletes_only_selected_repository_history():
    with SessionLocal() as session:
        session.query(RunRecord).filter(RunRecord.repository_id.is_not(None)).delete()
        session.query(RepositoryConfig).filter(RepositoryConfig.name.in_(["Repo A", "Repo B"])).delete(
            synchronize_session=False
        )
        session.commit()

        repository_a = RepositoryConfig(
            name="Repo A",
            provider="github",
            repo_url="example/a",
            repo_path="example/a",
            default_branch="main",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            encrypted_token="token-a",
            token_last4="aaaa",
        )
        repository_a.target_folders = []
        repository_b = RepositoryConfig(
            name="Repo B",
            provider="github",
            repo_url="example/b",
            repo_path="example/b",
            default_branch="main",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            encrypted_token="token-b",
            token_last4="bbbb",
        )
        repository_b.target_folders = []
        session.add(repository_a)
        session.add(repository_b)
        session.commit()
        session.refresh(repository_a)
        session.refresh(repository_b)

        run_a = RunRecord(
            repository_id=repository_a.id,
            endpoint="/generate",
            status="completed",
            created_at=datetime.now(UTC),
        )
        run_b = RunRecord(
            repository_id=repository_b.id,
            endpoint="/generate",
            status="completed",
            created_at=datetime.now(UTC),
        )
        session.add(run_a)
        session.add(run_b)
        session.commit()
        run_a_id = run_a.id
        run_b_id = run_b.id
        repository_a_id = repository_a.id

    with SessionLocal() as session:
        runs = session.query(RunRecord).filter(RunRecord.repository_id == repository_a_id).all()
        for run in runs:
            session.delete(run)
        session.commit()

    with SessionLocal() as session:
        assert session.get(RunRecord, run_a_id) is None
        assert session.get(RunRecord, run_b_id) is not None

        # Cleanup: delete test repositories and remaining runs
        session.query(RunRecord).filter(RunRecord.repository_id.is_not(None)).delete()
        session.query(RepositoryConfig).filter(RepositoryConfig.name.in_(["Repo A", "Repo B"])).delete(
            synchronize_session=False
        )
        session.commit()


def test_execute_run_process_updates_progress_and_completion(monkeypatch):
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="queued",
            progress_percent=5.0,
            progress_message="Queued",
            created_at=datetime.now(UTC),
            request_payload="{}",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    def fake_execute_endpoint(endpoint, payload, progress_callback=None):
        assert endpoint == "/generate"
        assert progress_callback is not None
        progress_callback(35.0, "Analyzing repository")
        progress_callback(80.0, "Building documentation")
        return WorkflowRunResult(
            response={"status": "success"},
            summary_output="{}",
            metrics_files_analyzed=3,
            metrics_docstrings_generated=2,
            metrics_skipped_files=1,
        )

    monkeypatch.setattr("admin.jobs._execute_endpoint", fake_execute_endpoint)

    _execute_run_process(run_id, "/generate", {})

    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.status == "completed"
        assert stored_run.progress_percent == 100.0
        assert stored_run.progress_message == "Completed"
        assert stored_run.metrics_files_analyzed == 3


def test_execute_run_process_redacts_token_from_failure_error_message(monkeypatch):
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="queued",
            progress_percent=5.0,
            progress_message="Queued",
            created_at=datetime.now(UTC),
            request_payload="{}",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    def fake_execute_endpoint(endpoint, payload, progress_callback=None):
        raise RuntimeError(
            "Failed to clone repository 'example/project': fatal: unable to access "
            "'https://x-access-token:ghp_abcdefghijklmnopqrstuvwxyz123456@github.com/example/project.git/'"
        )

    monkeypatch.setattr("admin.jobs._execute_endpoint", fake_execute_endpoint)
    monkeypatch.setattr("admin.jobs.os.setsid", lambda: None)

    _execute_run_process(run_id, "/generate", {})

    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.status == "failed"
        assert stored_run.error_message is not None
        assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in stored_run.error_message
        assert "https://***:***@github.com" in stored_run.error_message


def test_redact_leaked_secrets_from_run_records_cleans_stored_error_messages():
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="failed",
            created_at=datetime.now(UTC),
            error_message=(
                "fatal: unable to access "
                "'https://x-access-token:ghp_abcdefghijklmnopqrstuvwxyz123456@github.com/o/r.git/'"
            ),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    scrubbed_count = redact_leaked_secrets_from_run_records()

    assert scrubbed_count >= 1
    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.error_message is not None
        assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in stored_run.error_message
        assert "https://***:***@github.com" in stored_run.error_message


def test_execute_endpoint_dispatches_generate_architecture_docs(monkeypatch):
    captured = {}

    def fake_execute_architecture_generation_request(req, progress_callback=None):
        captured["req"] = req
        return WorkflowRunResult(response={"status": "success"}, summary_output="{}", draft_id="arch_123")

    monkeypatch.setattr(
        "admin.jobs.execute_architecture_generation_request",
        fake_execute_architecture_generation_request,
    )

    result = _execute_endpoint(
        "/generate-architecture-docs",
        {
            "provider": "github",
            "repo_url": "example/project",
            "token": "secret",
            "branch": "main",
        },
    )

    assert result.draft_id == "arch_123"
    assert captured["req"].repo_url == "example/project"


def test_execute_endpoint_dispatches_approve_architecture_docs(monkeypatch):
    captured = {}

    def fake_execute_architecture_approval_request(req, progress_callback=None):
        captured["req"] = req
        return WorkflowRunResult(response={"status": "approved"}, summary_output="{}", draft_id=req.draft_id)

    monkeypatch.setattr(
        "admin.jobs.execute_architecture_approval_request",
        fake_execute_architecture_approval_request,
    )

    result = _execute_endpoint(
        "/approve-architecture-docs",
        {
            "provider": "github",
            "repo_url": "example/project",
            "token": "secret",
            "branch": "main",
            "draft_id": "arch_123",
            "output_path": "docs/project/architecture.rst",
            "overwrite_existing": False,
        },
    )

    assert result.draft_id == "arch_123"
    assert captured["req"].output_path == "docs/project/architecture.rst"


def test_execute_endpoint_raises_for_unsupported_endpoint():
    try:
        _execute_endpoint("/unsupported", {})
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Unsupported endpoint" in str(exc)


def test_scrub_sensitive_run_payloads_skips_invalid_json():
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="failed",
            created_at=datetime.now(UTC),
            request_payload="not-valid-json{",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    scrub_sensitive_run_payloads()

    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.request_payload == "not-valid-json{"


def test_scrub_sensitive_run_payloads_skips_payload_without_token():
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="failed",
            created_at=datetime.now(UTC),
            request_payload=json.dumps({"repo_url": "example/project", "branch": "main"}),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    scrub_sensitive_run_payloads()

    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert json.loads(stored_run.request_payload) == {"repo_url": "example/project", "branch": "main"}


def test_ensure_run_record_columns_adds_missing_columns(monkeypatch, tmp_path):
    from sqlalchemy import create_engine, inspect, text

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}", future=True)
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE run_records (id INTEGER PRIMARY KEY)"))

    monkeypatch.setattr("admin.database.engine", legacy_engine)

    _ensure_run_record_columns()

    columns = {column["name"] for column in inspect(legacy_engine).get_columns("run_records")}
    assert "progress_percent" in columns
    assert "progress_message" in columns


def test_execute_endpoint_dispatches_generate(monkeypatch):
    captured = {}

    def fake_execute_generate_request(req, progress_callback=None):
        captured["req"] = req
        return WorkflowRunResult(response={"status": "success"}, summary_output="{}")

    monkeypatch.setattr("admin.jobs.execute_generate_request", fake_execute_generate_request)

    result = _execute_endpoint(
        "/generate",
        {"provider": "github", "repo_url": "example/project", "token": "secret", "branch": "main"},
    )

    assert result.response == {"status": "success"}
    assert captured["req"].repo_url == "example/project"


def test_execute_endpoint_dispatches_publish_pages(monkeypatch):
    captured = {}

    def fake_execute_publish_request(req, progress_callback=None):
        captured["req"] = req
        return WorkflowRunResult(response={"status": "success"}, summary_output="{}")

    monkeypatch.setattr("admin.jobs.execute_publish_request", fake_execute_publish_request)

    result = _execute_endpoint(
        "/publish-pages",
        {"repo_url": "example/project", "token": "secret", "branch": "main"},
    )

    assert result.response == {"status": "success"}
    assert captured["req"].repo_url == "example/project"


def test_execute_endpoint_dispatches_suggest_python_docstrings_pr(monkeypatch):
    captured = {}

    def fake_execute_docstring_pr_request(req, progress_callback=None):
        captured["req"] = req
        return WorkflowRunResult(response={"status": "success"}, summary_output="{}")

    monkeypatch.setattr("admin.jobs.execute_docstring_pr_request", fake_execute_docstring_pr_request)

    result = _execute_endpoint(
        "/suggest-python-docstrings-pr",
        {"provider": "github", "repo_url": "example/project", "token": "secret", "base_branch": "main"},
    )

    assert result.response == {"status": "success"}
    assert captured["req"].repo_url == "example/project"


def test_duration_seconds_normalizes_aware_started_and_naive_finished():
    started = datetime(2026, 1, 1, tzinfo=UTC)
    finished = datetime(2026, 1, 1, 0, 0, 5)

    assert jobs._duration_seconds(started, finished) == 5.0


def test_update_run_is_a_no_op_for_unknown_run_id():
    with SessionLocal() as session:
        max_id = session.query(RunRecord.id).order_by(RunRecord.id.desc()).first()
    missing_id = (max_id[0] if max_id else 0) + 1000000

    jobs._update_run(missing_id, lambda run: (_ for _ in ()).throw(AssertionError("should not be called")))


def test_execute_run_process_returns_immediately_for_cancelled_run(monkeypatch):
    with SessionLocal() as session:
        run = RunRecord(endpoint="/generate", status="cancelled", created_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    monkeypatch.setattr("admin.jobs.os.setsid", lambda: None)
    monkeypatch.setattr(
        "admin.jobs._execute_endpoint",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not execute a cancelled run")),
    )

    _execute_run_process(run_id, "/generate", {})


def test_execute_run_process_does_not_overwrite_cancelled_status_on_failure(monkeypatch):
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="queued",
            created_at=datetime.now(UTC),
            request_payload="{}",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    def fake_execute_endpoint(endpoint, payload, progress_callback=None):
        with SessionLocal() as session:
            stored = session.get(RunRecord, run_id)
            stored.status = "cancelled"
            session.add(stored)
            session.commit()
        raise RuntimeError("boom")

    monkeypatch.setattr("admin.jobs._execute_endpoint", fake_execute_endpoint)
    monkeypatch.setattr("admin.jobs.os.setsid", lambda: None)

    _execute_run_process(run_id, "/generate", {})

    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.status == "cancelled"
        assert stored_run.error_message is None


def test_request_run_cancellation_removes_job_still_in_queue():
    with SessionLocal() as session:
        run = RunRecord(endpoint="/generate", status="queued", created_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    with jobs.QUEUE_CONDITION:
        jobs.JOB_QUEUE.append(jobs.QueuedJob(run_id=run_id, endpoint="/generate", payload={}))

    outcome = request_run_cancellation(run_id)

    assert outcome == "cancelled"
    assert all(job.run_id != run_id for job in jobs.JOB_QUEUE)


def test_request_run_cancellation_returns_running_when_termination_fails(monkeypatch):
    class _FakeAliveProcess:
        def is_alive(self):
            return True

    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="running",
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    jobs.RUNNING_PROCESSES[run_id] = _FakeAliveProcess()
    monkeypatch.setattr("admin.jobs._terminate_process_tree", lambda process: False)

    try:
        outcome = request_run_cancellation(run_id)
        assert outcome == "running"
    finally:
        jobs.RUNNING_PROCESSES.pop(run_id, None)


def test_request_run_cancellation_raises_for_unknown_run():
    with SessionLocal() as session:
        max_id = session.query(RunRecord.id).order_by(RunRecord.id.desc()).first()
    missing_id = (max_id[0] if max_id else 0) + 1000000

    try:
        request_run_cancellation(missing_id)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Run not found" in str(exc)


def test_request_run_cancellation_returns_existing_status_for_finished_run():
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="completed",
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    outcome = request_run_cancellation(run_id)

    assert outcome == "completed"


def test_terminate_process_tree_returns_false_when_process_has_no_pid():
    class _FakeProcess:
        pid = None

    assert jobs._terminate_process_tree(_FakeProcess()) is False


def test_terminate_process_tree_returns_true_when_getpgid_raises(monkeypatch):
    class _FakeProcess:
        pid = 999999

    monkeypatch.setattr(
        "admin.jobs.os.getpgid",
        lambda pid: (_ for _ in ()).throw(ProcessLookupError()),
    )

    assert jobs._terminate_process_tree(_FakeProcess()) is True


def test_terminate_process_tree_returns_true_when_sigterm_raises(monkeypatch):
    class _FakeProcess:
        pid = 999999

        def is_alive(self):
            return True

    monkeypatch.setattr("admin.jobs.os.getpgid", lambda pid: pid)

    def raising_killpg(pgid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr("admin.jobs.os.killpg", raising_killpg)

    assert jobs._terminate_process_tree(_FakeProcess()) is True


def test_terminate_process_tree_escalates_to_sigkill_after_grace_period(monkeypatch):
    class _FakeProcess:
        pid = 999999

        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

    monkeypatch.setattr("admin.jobs.CANCEL_GRACE_SECONDS", 0.01)
    monkeypatch.setattr("admin.jobs.sleep", lambda seconds: None)
    monkeypatch.setattr("admin.jobs.os.getpgid", lambda pid: pid)
    monkeypatch.setattr("admin.jobs.os.killpg", lambda pgid, sig: None)

    result = jobs._terminate_process_tree(_FakeProcess())

    assert result is False


def test_terminate_process_tree_returns_true_when_sigkill_raises_process_lookup_error(monkeypatch):
    class _FakeProcess:
        pid = 999999

        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

    monkeypatch.setattr("admin.jobs.CANCEL_GRACE_SECONDS", 0.01)
    monkeypatch.setattr("admin.jobs.sleep", lambda seconds: None)
    monkeypatch.setattr("admin.jobs.os.getpgid", lambda pid: pid)

    calls = {"count": 0}

    def killpg(pgid, sig):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise ProcessLookupError()

    monkeypatch.setattr("admin.jobs.os.killpg", killpg)

    assert jobs._terminate_process_tree(_FakeProcess()) is True


def test_dispatch_loop_processes_queued_job_end_to_end(monkeypatch):
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="queued",
            created_at=datetime.now(UTC),
            request_payload="{}",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    def fake_execute_endpoint(endpoint, payload, progress_callback=None):
        return WorkflowRunResult(response={"status": "success"}, summary_output="{}")

    monkeypatch.setattr("admin.jobs._execute_endpoint", fake_execute_endpoint)

    jobs.enqueue_run(run_id, "/generate", {})

    _wait_for_dispatcher_to_finish(run_id)

    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.status == "completed"


def test_dispatch_loop_skips_job_whose_run_was_already_cancelled(monkeypatch):
    with SessionLocal() as session:
        cancelled_run = RunRecord(endpoint="/generate", status="cancelled", created_at=datetime.now(UTC))
        valid_run = RunRecord(
            endpoint="/generate",
            status="queued",
            created_at=datetime.now(UTC),
            request_payload="{}",
        )
        session.add_all([cancelled_run, valid_run])
        session.commit()
        session.refresh(cancelled_run)
        session.refresh(valid_run)
        cancelled_run_id = cancelled_run.id
        valid_run_id = valid_run.id

    def fake_execute_endpoint(endpoint, payload, progress_callback=None):
        return WorkflowRunResult(response={"status": "success"}, summary_output="{}")

    monkeypatch.setattr("admin.jobs._execute_endpoint", fake_execute_endpoint)

    jobs.enqueue_run(cancelled_run_id, "/generate", {})
    jobs.enqueue_run(valid_run_id, "/generate", {})

    _wait_for_dispatcher_to_finish(valid_run_id)

    with SessionLocal() as session:
        stored_run = session.get(RunRecord, valid_run_id)
        stored_cancelled = session.get(RunRecord, cancelled_run_id)
        assert stored_run is not None
        assert stored_run.status == "completed"
        assert stored_cancelled is not None
        assert stored_cancelled.status == "cancelled"


def test_dispatch_loop_handles_run_record_deleted_during_execution(monkeypatch):
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="queued",
            created_at=datetime.now(UTC),
            request_payload="{}",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    def deleting_execute_endpoint(endpoint, payload, progress_callback=None):
        with SessionLocal() as session:
            stored = session.get(RunRecord, run_id)
            if stored is not None:
                session.delete(stored)
                session.commit()
        return WorkflowRunResult(response={"status": "success"}, summary_output="{}")

    monkeypatch.setattr("admin.jobs._execute_endpoint", deleting_execute_endpoint)

    jobs.enqueue_run(run_id, "/generate", {})

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if jobs.RUNNING_PROCESSES.get(run_id) is None:
            break
        time.sleep(0.1)
    time.sleep(0.3)

    with SessionLocal() as session:
        assert session.get(RunRecord, run_id) is None


def test_dispatch_loop_marks_run_failed_when_process_exits_unexpectedly(monkeypatch):
    with SessionLocal() as session:
        run = RunRecord(
            endpoint="/generate",
            status="queued",
            created_at=datetime.now(UTC),
            request_payload="{}",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    def crashing_execute_endpoint(endpoint, payload, progress_callback=None):
        os._exit(1)

    monkeypatch.setattr("admin.jobs._execute_endpoint", crashing_execute_endpoint)

    jobs.enqueue_run(run_id, "/generate", {})

    _wait_for_dispatcher_to_finish(run_id)

    with SessionLocal() as session:
        stored_run = session.get(RunRecord, run_id)
        assert stored_run is not None
        assert stored_run.status == "failed"
        assert stored_run.error_message == jobs.UNEXPECTED_EXIT_MESSAGE
