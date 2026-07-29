import json
from asyncio import run
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import HTTPException

from admin.database import SessionLocal
from admin.models import RepositoryConfig, RunRecord
from admin.router import (
    _build_architecture_generation_request,
    _read_artifact_preview,
    _run_log_entries,
    _safe_request_payload,
    clear_runs,
    create_repository,
    dashboard,
    delete_repository,
    download_artifact,
    login_page,
    login_submit,
    logout,
    preview_artifact,
    repositories_page,
    repository_detail,
    retry_run,
    run_detail,
    runs_page,
    trigger_approve_architecture_docs,
    trigger_generate,
    trigger_generate_architecture_docs,
    trigger_publish,
    trigger_suggest_pr,
    update_repository,
)
from admin.security import create_admin_session, encrypt_token


class _FakeRequest:
    def __init__(self, headers=None, cookies=None):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.url = SimpleNamespace(path="/admin/test")


def test_login_page_renders_form_when_signed_out(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "secret")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(login_page(request=_FakeRequest()))

    assert response.status_code == 200


def test_login_page_redirects_when_already_signed_in(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    session_value = create_admin_session("admin")

    response = run(login_page(request=_FakeRequest(cookies={"autodoc_admin_session": session_value})))

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_login_submit_rejects_invalid_credentials(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "secret")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(
        login_submit(
            request=_FakeRequest(),
            _=None,
            username="admin",
            password="wrong-password",
        )
    )

    assert response.status_code == 401


def test_login_submit_sets_session_cookie_on_success(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_USERNAME", "admin")
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "secret")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(
        login_submit(
            request=_FakeRequest(),
            _=None,
            username="admin",
            password="secret",
        )
    )

    assert response.status_code == 303
    assert "autodoc_admin_session" in response.headers.get("set-cookie", "")


def test_logout_clears_session_cookie(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(logout(request=_FakeRequest(), _=None))

    assert response.status_code == 303
    set_cookie = response.headers.get("set-cookie", "")
    assert "autodoc_admin_session=" in set_cookie


def test_dashboard_renders_with_no_repositories(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(dashboard(request=_FakeRequest(), admin_user="tester"))

    assert response.status_code == 200


def test_repositories_page_renders(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(repositories_page(request=_FakeRequest(), admin_user="tester"))

    assert response.status_code == 200


def test_runs_page_renders(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(runs_page(request=_FakeRequest(), repository_id=None, admin_user="tester"))

    assert response.status_code == 200


def test_repository_crud_lifecycle_through_router_handlers(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "CRUD Lifecycle Repo").delete()
        session.commit()

    create_response = run(
        create_repository(
            request=_FakeRequest(),
            admin_user="tester",
            _=None,
            name="CRUD Lifecycle Repo",
            provider="github",
            repo_url="https://github.com/example/crud-project",
            default_branch="main",
            target_folders="",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            token="secret-token",
        )
    )
    assert create_response.status_code == 303
    repository_id = int(create_response.headers["location"].rsplit("/", 1)[-1])

    try:
        detail_response = run(
            repository_detail(repository_id=repository_id, request=_FakeRequest(), admin_user="tester")
        )
        assert detail_response.status_code == 200

        update_response = run(
            update_repository(
                repository_id=repository_id,
                request=_FakeRequest(),
                admin_user="tester",
                _=None,
                name="CRUD Lifecycle Repo Renamed",
                provider="github",
                repo_url="https://github.com/example/crud-project",
                default_branch="main",
                target_folders="",
                preferred_model="gpt-4o-mini",
                reuse_doc=False,
                docstring_threshold=0.5,
                low_content_min_lines=4,
                token="",
            )
        )
        assert update_response.status_code == 303

        with SessionLocal() as session:
            updated = session.get(RepositoryConfig, repository_id)
            assert updated is not None
            assert updated.name == "CRUD Lifecycle Repo Renamed"
    finally:
        delete_response = run(
            delete_repository(
                repository_id=repository_id,
                request=_FakeRequest(),
                admin_user="tester",
                _=None,
            )
        )
        assert delete_response.status_code == 303

        with SessionLocal() as session:
            assert session.get(RepositoryConfig, repository_id) is None


def test_trigger_publish_enqueues_run(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    captured = {}

    def fake_enqueue_run(run_id, endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload

    monkeypatch.setattr("admin.router.enqueue_run", fake_enqueue_run)

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "Publish Trigger Repo").delete()
        session.commit()
        repository = RepositoryConfig(
            name="Publish Trigger Repo",
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
            trigger_publish(
                repository_id=repository_id,
                request=_FakeRequest(),
                admin_user="tester",
                _=None,
                branch="",
                low_content_min_lines=4,
            )
        )

        assert response.status_code == 303
        assert captured["endpoint"] == "/publish-pages"
        assert captured["payload"]["token"] == "secret-token"
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.repository_id == repository_id).delete()
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()


def test_trigger_suggest_pr_rejects_non_github_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "GitLab Suggest Repo").delete()
        session.commit()
        repository = RepositoryConfig(
            name="GitLab Suggest Repo",
            provider="gitlab",
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
        raised = None
        try:
            run(
                trigger_suggest_pr(
                    repository_id=repository_id,
                    request=_FakeRequest(),
                    admin_user="tester",
                    _=None,
                    base_branch="",
                    suggestion_branch="",
                    title="Add suggested docstrings",
                    max_docstrings=50,
                )
            )
        except HTTPException as exc:
            raised = exc
        assert raised is not None
        assert raised.status_code == 422
    finally:
        with SessionLocal() as session:
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()


def test_clear_runs_deletes_all_runs_when_no_repository_selected():
    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    response = run(
        clear_runs(
            request=_FakeRequest(),
            admin_user="tester",
            _=None,
            repository_id=None,
        )
    )

    assert response.status_code == 303
    with SessionLocal() as session:
        assert session.get(RunRecord, run_id) is None


def test_run_detail_renders_for_existing_run(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(run_detail(run_id=run_id, request=_FakeRequest(), admin_user="tester"))
        assert response.status_code == 200
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_run_detail_raises_404_for_missing_run():
    raised = None
    try:
        run(run_detail(run_id=999_999_999, request=_FakeRequest(), admin_user="tester"))
    except HTTPException as exc:
        raised = exc
    assert raised is not None
    assert raised.status_code == 404


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


def test_download_artifact_serves_file_within_artifact_dir(tmp_path):
    artifact_dir = tmp_path / "run1"
    artifact_dir.mkdir()
    (artifact_dir / "report.txt").write_text("hello", encoding="utf-8")

    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/generate",
            status="completed",
            created_at=datetime.now(UTC),
            artifact_dir=str(artifact_dir),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(
            download_artifact(
                run_id=run_id,
                artifact_name="report.txt",
                request=_FakeRequest(),
                admin_user="tester",
            )
        )

        assert response.status_code == 200
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_download_artifact_rejects_sibling_directory_sharing_a_name_prefix(tmp_path):
    # Regression test: a naive `str(target).startswith(str(artifact_dir))` check
    # incorrectly treats "run12" as being inside "run1" because one string
    # prefixes the other; `is_relative_to` must reject this.
    artifact_dir = tmp_path / "run1"
    artifact_dir.mkdir()
    sibling_dir = tmp_path / "run12"
    sibling_dir.mkdir()
    (sibling_dir / "secret.txt").write_text("nope", encoding="utf-8")

    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/generate",
            status="completed",
            created_at=datetime.now(UTC),
            artifact_dir=str(artifact_dir),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        raised = None
        try:
            run(
                download_artifact(
                    run_id=run_id,
                    artifact_name="../run12/secret.txt",
                    request=_FakeRequest(),
                    admin_user="tester",
                )
            )
        except HTTPException as exc:
            raised = exc
        assert raised is not None
        assert raised.status_code == 403
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_download_artifact_rejects_missing_artifact_dir():
    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/generate",
            status="failed",
            created_at=datetime.now(UTC),
            artifact_dir=None,
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        raised = None
        try:
            run(
                download_artifact(
                    run_id=run_id,
                    artifact_name="report.txt",
                    request=_FakeRequest(),
                    admin_user="tester",
                )
            )
        except HTTPException as exc:
            raised = exc
        assert raised is not None
        assert raised.status_code == 403
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_preview_artifact_rejects_sibling_directory_sharing_a_name_prefix(tmp_path):
    artifact_dir = tmp_path / "run1"
    artifact_dir.mkdir()
    sibling_dir = tmp_path / "run12"
    sibling_dir.mkdir()
    (sibling_dir / "secret.txt").write_text("nope", encoding="utf-8")

    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/generate",
            status="completed",
            created_at=datetime.now(UTC),
            artifact_dir=str(artifact_dir),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        raised = None
        try:
            run(
                preview_artifact(
                    run_id=run_id,
                    artifact_name="../run12/secret.txt",
                    request=_FakeRequest(),
                    admin_user="tester",
                )
            )
        except HTTPException as exc:
            raised = exc
        assert raised is not None
        assert raised.status_code == 403
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


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
