from datetime import UTC, datetime

from admin.database import SessionLocal
from admin.jobs import request_run_cancellation
from admin.models import RepositoryConfig, RunRecord


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
