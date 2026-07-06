from datetime import UTC, datetime

from admin.database import SessionLocal
from admin.jobs import _execute_endpoint, _execute_run_process, reconcile_interrupted_runs, request_run_cancellation
from admin.models import RepositoryConfig, RunRecord
from services.workflow_service import WorkflowRunResult


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
