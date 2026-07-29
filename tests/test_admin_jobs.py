import json
import os
import time
from datetime import UTC, datetime
from multiprocessing import Process

import admin.jobs as jobs
from admin.database import SessionLocal, redact_leaked_secrets_from_run_records, scrub_sensitive_run_payloads
from admin.jobs import _execute_endpoint, _execute_run_process, reconcile_interrupted_runs, request_run_cancellation
from admin.models import RepositoryConfig, RunRecord
from services.workflow_service import WorkflowRunResult


def _isolated_sleep_target(seconds: float) -> None:
    os.setsid()
    time.sleep(seconds)


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
