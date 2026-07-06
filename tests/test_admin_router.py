import json
from asyncio import run
from datetime import UTC, datetime
from types import SimpleNamespace

from admin.database import SessionLocal
from admin.models import RepositoryConfig, RunRecord
from admin.router import (
    _build_architecture_generation_request,
    _read_artifact_preview,
    _run_log_entries,
    _safe_request_payload,
    retry_run,
    trigger_approve_architecture_docs,
    trigger_generate,
    trigger_generate_architecture_docs,
)
from admin.security import encrypt_token


class _FakeRequest:
    def __init__(self):
        self.headers = {}
        self.cookies = {}
        self.url = SimpleNamespace(path="/admin/test")


def test_run_log_entries_prioritize_key_logs(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "app.log").write_text("app\n", encoding="utf-8")
    (artifact_dir / "sphinx_build.log").write_text("sphinx\n", encoding="utf-8")
    (artifact_dir / "skipped_autoapi_files.txt").write_text("skip\n", encoding="utf-8")
    (artifact_dir / "notes.json").write_text("{}", encoding="utf-8")

    run = SimpleNamespace(
        artifact_dir=str(artifact_dir),
        log_path=str(artifact_dir / "app.log"),
    )

    entries = _run_log_entries(run)

    assert [entry["name"] for entry in entries] == [
        "app.log",
        "sphinx_build.log",
        "skipped_autoapi_files.txt",
    ]


def test_read_artifact_preview_truncates_large_files(tmp_path):
    artifact_path = tmp_path / "sphinx_build.log"
    artifact_path.write_text("x" * 20, encoding="utf-8")

    content, truncated = _read_artifact_preview(artifact_path, max_chars=10)

    assert content == "x" * 10
    assert truncated is True


def test_build_architecture_generation_request_uses_repository_defaults(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    repository = RepositoryConfig(
        name="Arch Builder Repo",
        provider="github",
        repo_url="example/project",
        repo_path="example/project",
        default_branch="main",
        preferred_model="gpt-4o-mini",
        reuse_doc=False,
        docstring_threshold=0.5,
        low_content_min_lines=4,
        encrypted_token=encrypt_token("secret-token"),
        token_last4="oken",
    )
    repository.target_folders = ["src"]

    req = _build_architecture_generation_request(repository)

    assert req.provider == "github"
    assert req.repo_url == "example/project"
    assert req.token == "secret-token"
    assert req.branch == "main"
    assert req.target_folders == ["src"]
    assert req.output_path == "docs/project/architecture.rst"
    assert req.include_diagrams is True
    assert req.reuse_existing_docs is True


def test_safe_request_payload_excludes_token():
    payload = {
        "repo_url": "example/project",
        "token": "secret-token",
        "branch": "main",
    }

    assert _safe_request_payload(payload) == {
        "repo_url": "example/project",
        "branch": "main",
    }


def test_trigger_generate_stores_sanitized_payload_and_enqueues_secret(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    captured = {}

    def fake_enqueue_run(run_id, endpoint, payload):
        captured["run_id"] = run_id
        captured["endpoint"] = endpoint
        captured["payload"] = payload

    monkeypatch.setattr("admin.router.enqueue_run", fake_enqueue_run)

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "Generate Trigger Repo").delete()
        session.commit()
        repository = RepositoryConfig(
            name="Generate Trigger Repo",
            provider="github",
            repo_url="example/project",
            repo_path="example/project",
            default_branch="main",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            encrypted_token=encrypt_token("secret-token"),
            token_last4="oken",
        )
        repository.target_folders = []
        session.add(repository)
        session.commit()
        session.refresh(repository)
        repository_id = repository.id

    try:
        response = run(
            trigger_generate(
                repository_id=repository_id,
                request=_FakeRequest(),
                admin_user="tester",
                _=None,
                branch="",
                target_folders="",
                preferred_model="",
                reuse_doc=False,
                docstring_threshold=0.5,
                low_content_min_lines=4,
            )
        )

        assert response.status_code == 303
        assert captured["endpoint"] == "/generate"
        assert captured["payload"]["token"] == "secret-token"

        with SessionLocal() as session:
            run_record = session.get(RunRecord, captured["run_id"])
            assert run_record is not None
            stored_payload = json.loads(run_record.request_payload)
            assert "token" not in stored_payload
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.repository_id == repository_id).delete()
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()


def test_trigger_generate_architecture_docs_enqueues_run(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    captured = {}

    def fake_enqueue_run(run_id, endpoint, payload):
        captured["run_id"] = run_id
        captured["endpoint"] = endpoint
        captured["payload"] = payload

    monkeypatch.setattr("admin.router.enqueue_run", fake_enqueue_run)

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "Arch Trigger Repo").delete()
        session.commit()
        repository = RepositoryConfig(
            name="Arch Trigger Repo",
            provider="github",
            repo_url="example/project",
            repo_path="example/project",
            default_branch="main",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            encrypted_token=encrypt_token("secret-token"),
            token_last4="oken",
        )
        repository.target_folders = []
        session.add(repository)
        session.commit()
        session.refresh(repository)
        repository_id = repository.id

    try:
        response = run(
            trigger_generate_architecture_docs(
                repository_id=repository_id,
                request=_FakeRequest(),
                admin_user="tester",
                _=None,
                branch="",
                target_folders="",
                output_path="docs/project/architecture.rst",
                include_diagrams=True,
                reuse_existing_docs=True,
            )
        )

        assert response.status_code == 303
        assert captured["endpoint"] == "/generate-architecture-docs"
        assert captured["payload"]["repo_url"] == "example/project"

        with SessionLocal() as session:
            run_record = session.get(RunRecord, captured["run_id"])
            assert run_record is not None
            assert run_record.endpoint == "/generate-architecture-docs"
            stored_payload = json.loads(run_record.request_payload)
            assert "token" not in stored_payload
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.repository_id == repository_id).delete()
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()


def test_trigger_approve_architecture_docs_requires_generation_run():
    from fastapi import HTTPException

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        raised = None
        try:
            run(
                trigger_approve_architecture_docs(
                    run_id=run_id,
                    request=_FakeRequest(),
                    admin_user="tester",
                    _=None,
                    overwrite_existing=False,
                    approval_note="",
                )
            )
        except HTTPException as exc:
            raised = exc
        assert raised is not None
        assert raised.status_code == 422
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_trigger_approve_architecture_docs_enqueues_approval_run(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    captured = {}

    def fake_enqueue_run(run_id, endpoint, payload):
        captured["run_id"] = run_id
        captured["endpoint"] = endpoint
        captured["payload"] = payload

    monkeypatch.setattr("admin.router.enqueue_run", fake_enqueue_run)

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "Arch Approval Repo").delete()
        session.commit()
        repository = RepositoryConfig(
            name="Arch Approval Repo",
            provider="github",
            repo_url="example/project",
            repo_path="example/project",
            default_branch="main",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            encrypted_token=encrypt_token("secret-token"),
            token_last4="oken",
        )
        repository.target_folders = []
        session.add(repository)
        session.commit()
        session.refresh(repository)
        repository_id = repository.id

        run_record = RunRecord(
            repository_id=repository_id,
            endpoint="/generate-architecture-docs",
            status="completed",
            source_branch="main",
            created_at=datetime.now(UTC),
            result_payload=json.dumps(
                {"draft_id": "arch_123", "proposed_output_path": "docs/project/architecture.rst"}
            ),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(
            trigger_approve_architecture_docs(
                run_id=run_id,
                request=_FakeRequest(),
                admin_user="tester",
                _=None,
                overwrite_existing=True,
                approval_note="Looks good",
            )
        )

        assert response.status_code == 303
        assert captured["endpoint"] == "/approve-architecture-docs"
        assert captured["payload"]["draft_id"] == "arch_123"
        assert captured["payload"]["overwrite_existing"] is True
        with SessionLocal() as session:
            run_record = session.get(RunRecord, captured["run_id"])
            assert run_record is not None
            stored_payload = json.loads(run_record.request_payload)
            assert "token" not in stored_payload
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.repository_id == repository_id).delete()
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()


def test_retry_run_rehydrates_token_from_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    captured = {}

    def fake_enqueue_run(run_id, endpoint, payload):
        captured["run_id"] = run_id
        captured["endpoint"] = endpoint
        captured["payload"] = payload

    monkeypatch.setattr("admin.router.enqueue_run", fake_enqueue_run)

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "Retry Repo").delete()
        session.commit()
        repository = RepositoryConfig(
            name="Retry Repo",
            provider="github",
            repo_url="example/project",
            repo_path="example/project",
            default_branch="main",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            encrypted_token=encrypt_token("secret-token"),
            token_last4="oken",
        )
        repository.target_folders = []
        session.add(repository)
        session.commit()
        session.refresh(repository)
        repository_id = repository.id

        run_record = RunRecord(
            repository_id=repository_id,
            endpoint="/generate",
            status="failed",
            created_at=datetime.now(UTC),
            request_payload=json.dumps(
                {
                    "provider": "github",
                    "repo_url": "example/project",
                    "branch": "main",
                    "target_folders": [],
                    "model": "gpt-4o-mini",
                    "reuse_doc": False,
                    "docstring_threshold": 0.5,
                    "low_content_min_lines": 4,
                }
            ),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(
            retry_run(
                run_id=run_id,
                request=_FakeRequest(),
                admin_user="tester",
                _=None,
            )
        )

        assert response.status_code == 303
        assert captured["endpoint"] == "/generate"
        assert captured["payload"]["token"] == "secret-token"

        with SessionLocal() as session:
            retry_record = session.get(RunRecord, captured["run_id"])
            assert retry_record is not None
            retry_payload = json.loads(retry_record.request_payload)
            assert "token" not in retry_payload
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.repository_id == repository_id).delete()
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()
