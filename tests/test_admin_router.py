import json
from asyncio import run
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from fastapi import HTTPException, Request

from admin.database import SessionLocal
from admin.models import RepositoryConfig, RunRecord
from admin.router import (
    _database_label,
    _fmt_duration,
    _json_loads,
    _status_badge_classes,
    cancel_run,
    clear_runs,
    create_repository,
    dashboard,
    delete_repository,
    download_artifact,
    duplicate_repository,
    login_page,
    login_submit,
    logout,
    preview_artifact,
    recent_activity_fragment,
    repositories_page,
    repository_detail,
    repository_edit_form,
    repository_new_form,
    retry_run,
    run_detail,
    run_row_fragment,
    run_status_fragment,
    runs_page,
    trigger_approve_architecture_docs,
    trigger_generate,
    trigger_generate_architecture_docs,
    trigger_publish,
    trigger_suggest_pr,
    update_repository,
)
from admin.security import create_admin_session, encrypt_token
from admin.services import (
    build_architecture_generation_request,
    build_pr_request,
    default_suggestion_branch,
    load_docstring_suggestions,
    load_language_summary,
    log_snippet,
    parse_target_folders,
    queue_payload_with_repository_secret,
    read_artifact_preview,
    run_log_entries,
    safe_request_payload,
    validate_provider,
    validate_repo_form,
)


class _FakeRequest:
    def __init__(self, headers=None, cookies=None):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.url = SimpleNamespace(path="/admin/test")


def _fake_request(headers=None, cookies=None) -> Request:
    return cast(Request, _FakeRequest(headers=headers, cookies=cookies))


def _make_repository(name, **overrides):
    defaults = dict(
        name=name,
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
    defaults.update(overrides)
    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == name).delete()
        session.commit()
        repository = RepositoryConfig(**defaults)
        repository.target_folders = []
        session.add(repository)
        session.commit()
        session.refresh(repository)
        return repository.id


def _delete_repository_and_runs(repository_id):
    with SessionLocal() as session:
        session.query(RunRecord).filter(RunRecord.repository_id == repository_id).delete()
        session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
        session.commit()


def _assert_raises_http_exception(coro, status_code):
    raised = None
    try:
        run(coro)
    except HTTPException as exc:
        raised = exc
    assert raised is not None
    assert raised.status_code == status_code
    return raised


def test_login_page_renders_form_when_signed_out(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "secret")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(login_page(request=_fake_request()))

    assert response.status_code == 200


def test_login_page_redirects_when_already_signed_in(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    session_value = create_admin_session("admin")

    response = run(login_page(request=_fake_request(cookies={"autodoc_admin_session": session_value})))

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_login_submit_rejects_invalid_credentials(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "secret")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(
        login_submit(
            request=_fake_request(),
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
            request=_fake_request(),
            _=None,
            username="admin",
            password="secret",
        )
    )

    assert response.status_code == 303
    assert "autodoc_admin_session" in response.headers.get("set-cookie", "")


def test_login_submit_reports_config_error_as_http_exception(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "")

    response = run(
        login_submit(
            request=_fake_request(),
            _=None,
            username="admin",
            password="secret",
        )
    )

    assert response.status_code == 503


def test_logout_clears_session_cookie(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(logout(request=_fake_request(), _=None))

    assert response.status_code == 303
    set_cookie = response.headers.get("set-cookie", "")
    assert "autodoc_admin_session=" in set_cookie


def test_redirect_returns_hx_redirect_header_for_htmx_requests(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(logout(request=_fake_request(headers={"HX-Request": "true"}), _=None))

    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/admin/login"


def test_dashboard_renders_with_no_repositories(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(dashboard(request=_fake_request(), admin_user="tester"))

    assert response.status_code == 200


def test_recent_activity_fragment_renders(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(recent_activity_fragment(request=_fake_request(), admin_user="tester"))

    assert response.status_code == 200


def test_repositories_page_renders(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(repositories_page(request=_fake_request(), admin_user="tester"))

    assert response.status_code == 200


def test_repository_new_form_renders(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(repository_new_form(request=_fake_request(), admin_user="tester"))

    assert response.status_code == 200


def test_runs_page_renders(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    response = run(runs_page(request=_fake_request(), repository_id=None, admin_user="tester"))

    assert response.status_code == 200


def test_runs_page_filters_by_repository_id(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    repository_id = _make_repository("Runs Filter Repo")

    try:
        response = run(runs_page(request=_fake_request(), repository_id=repository_id, admin_user="tester"))
        assert response.status_code == 200
    finally:
        _delete_repository_and_runs(repository_id)


def test_repository_crud_lifecycle_through_router_handlers(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "CRUD Lifecycle Repo").delete()
        session.commit()

    create_response = run(
        create_repository(
            request=_fake_request(),
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
    location = create_response.headers.get("location")
    assert location is not None
    repository_id = int(location.rsplit("/", 1)[-1])

    try:
        detail_response = run(
            repository_detail(repository_id=repository_id, request=_fake_request(), admin_user="tester")
        )
        assert detail_response.status_code == 200

        edit_form_response = run(
            repository_edit_form(repository_id=repository_id, request=_fake_request(), admin_user="tester")
        )
        assert edit_form_response.status_code == 200

        update_response = run(
            update_repository(
                repository_id=repository_id,
                request=_fake_request(),
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
                token="rotated-token",
            )
        )
        assert update_response.status_code == 303

        with SessionLocal() as session:
            updated = session.get(RepositoryConfig, repository_id)
            assert updated is not None
            assert updated.name == "CRUD Lifecycle Repo Renamed"
            assert updated.token_last4 == "oken"
    finally:
        delete_response = run(
            delete_repository(
                repository_id=repository_id,
                request=_fake_request(),
                admin_user="tester",
                _=None,
            )
        )
        assert delete_response.status_code == 303

        with SessionLocal() as session:
            assert session.get(RepositoryConfig, repository_id) is None


def test_create_repository_rejects_missing_token(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "No Token Repo").delete()
        session.commit()

    _assert_raises_http_exception(
        create_repository(
            request=_fake_request(),
            admin_user="tester",
            _=None,
            name="No Token Repo",
            provider="github",
            repo_url="https://github.com/example/no-token",
            default_branch="main",
            target_folders="",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            token="   ",
        ),
        422,
    )


def test_create_repository_rejects_duplicate_name(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    repository_id = _make_repository("Duplicate Name Repo")

    try:
        _assert_raises_http_exception(
            create_repository(
                request=_fake_request(),
                admin_user="tester",
                _=None,
                name="Duplicate Name Repo",
                provider="github",
                repo_url="https://github.com/example/dup",
                default_branch="main",
                target_folders="",
                preferred_model="gpt-4o-mini",
                reuse_doc=False,
                docstring_threshold=0.5,
                low_content_min_lines=4,
                token="secret-token",
            ),
            409,
        )
    finally:
        _delete_repository_and_runs(repository_id)


def test_repository_detail_raises_404_for_missing_repository():
    _assert_raises_http_exception(
        repository_detail(repository_id=999_999_999, request=_fake_request(), admin_user="tester"), 404
    )


def test_repository_edit_form_raises_404_for_missing_repository():
    _assert_raises_http_exception(
        repository_edit_form(repository_id=999_999_999, request=_fake_request(), admin_user="tester"), 404
    )


def test_update_repository_raises_404_for_missing_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    _assert_raises_http_exception(
        update_repository(
            repository_id=999_999_999,
            request=_fake_request(),
            admin_user="tester",
            _=None,
            name="Ghost Repo",
            provider="github",
            repo_url="https://github.com/example/ghost",
            default_branch="main",
            target_folders="",
            preferred_model="gpt-4o-mini",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
            token="",
        ),
        404,
    )


def test_delete_repository_raises_404_for_missing_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    _assert_raises_http_exception(
        delete_repository(repository_id=999_999_999, request=_fake_request(), admin_user="tester", _=None), 404
    )


def test_duplicate_repository_copies_config_with_unique_name(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    repository_id = _make_repository(
        "Duplicate Source Repo",
        preferred_model="gpt-4o-mini",
        reuse_doc=True,
        docstring_threshold=0.75,
        low_content_min_lines=8,
    )

    with SessionLocal() as session:
        session.query(RepositoryConfig).filter(RepositoryConfig.name == "Duplicate Source Repo (copy)").delete()
        session.commit()

    duplicate_ids = []
    try:
        response = run(
            duplicate_repository(repository_id=repository_id, request=_fake_request(), admin_user="tester", _=None)
        )
        assert response.status_code == 303
        location = response.headers.get("location")
        assert location is not None
        assert location.endswith("/edit")
        new_id = int(location.rsplit("/", 2)[-2])
        duplicate_ids.append(new_id)

        with SessionLocal() as session:
            source = session.get(RepositoryConfig, repository_id)
            duplicate = session.get(RepositoryConfig, new_id)
            assert duplicate is not None
            assert duplicate.name == "Duplicate Source Repo (copy)"
            assert duplicate.repo_url == source.repo_url
            assert duplicate.target_folders == source.target_folders
            assert duplicate.preferred_model == source.preferred_model
            assert duplicate.reuse_doc == source.reuse_doc
            assert duplicate.docstring_threshold == source.docstring_threshold
            assert duplicate.low_content_min_lines == source.low_content_min_lines
            assert duplicate.encrypted_token == source.encrypted_token
            assert duplicate.token_last4 == source.token_last4

        second_response = run(
            duplicate_repository(repository_id=repository_id, request=_fake_request(), admin_user="tester", _=None)
        )
        second_id = int(second_response.headers.get("location").rsplit("/", 2)[-2])
        duplicate_ids.append(second_id)

        with SessionLocal() as session:
            second_duplicate = session.get(RepositoryConfig, second_id)
            assert second_duplicate.name == "Duplicate Source Repo (copy 2)"
    finally:
        _delete_repository_and_runs(repository_id)
        for duplicate_id in duplicate_ids:
            _delete_repository_and_runs(duplicate_id)


def test_duplicate_repository_raises_404_for_missing_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    _assert_raises_http_exception(
        duplicate_repository(repository_id=999_999_999, request=_fake_request(), admin_user="tester", _=None), 404
    )


def test_trigger_generate_raises_404_for_missing_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    _assert_raises_http_exception(
        trigger_generate(
            repository_id=999_999_999,
            request=_fake_request(),
            admin_user="tester",
            _=None,
            branch="",
            target_folders="",
            preferred_model="",
            reuse_doc=False,
            docstring_threshold=0.5,
            low_content_min_lines=4,
        ),
        404,
    )


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
                request=_fake_request(),
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


def test_trigger_publish_raises_404_for_missing_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    _assert_raises_http_exception(
        trigger_publish(
            repository_id=999_999_999,
            request=_fake_request(),
            admin_user="tester",
            _=None,
            branch="",
            low_content_min_lines=4,
        ),
        404,
    )


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
        _assert_raises_http_exception(
            trigger_suggest_pr(
                repository_id=repository_id,
                request=_fake_request(),
                admin_user="tester",
                _=None,
                base_branch="",
                suggestion_branch="",
                title="Add suggested docstrings",
                max_docstrings=50,
            ),
            422,
        )
    finally:
        with SessionLocal() as session:
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()


def test_trigger_suggest_pr_raises_404_for_missing_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    _assert_raises_http_exception(
        trigger_suggest_pr(
            repository_id=999_999_999,
            request=_fake_request(),
            admin_user="tester",
            _=None,
            base_branch="",
            suggestion_branch="",
            title="Add suggested docstrings",
            max_docstrings=50,
        ),
        404,
    )


def test_trigger_suggest_pr_enqueues_run_for_github_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    captured = {}

    def fake_enqueue_run(run_id, endpoint, payload):
        captured["run_id"] = run_id
        captured["endpoint"] = endpoint
        captured["payload"] = payload

    monkeypatch.setattr("admin.router.enqueue_run", fake_enqueue_run)
    repository_id = _make_repository("Suggest PR Github Repo")

    try:
        response = run(
            trigger_suggest_pr(
                repository_id=repository_id,
                request=_fake_request(),
                admin_user="tester",
                _=None,
                base_branch="",
                suggestion_branch="",
                title="Add suggested docstrings",
                max_docstrings=50,
            )
        )

        assert response.status_code == 303
        assert captured["endpoint"] == "/suggest-docstrings-pr"
        assert captured["payload"]["token"] == "secret-token"
    finally:
        _delete_repository_and_runs(repository_id)


def test_trigger_generate_architecture_docs_raises_404_for_missing_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    _assert_raises_http_exception(
        trigger_generate_architecture_docs(
            repository_id=999_999_999,
            request=_fake_request(),
            admin_user="tester",
            _=None,
            branch="",
            target_folders="",
            output_path="docs/project/architecture.rst",
            include_diagrams=True,
            reuse_existing_docs=True,
        ),
        404,
    )


def test_clear_runs_deletes_all_runs_when_no_repository_selected():
    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    response = run(
        clear_runs(
            request=_fake_request(),
            admin_user="tester",
            _=None,
            repository_id=None,
        )
    )

    assert response.status_code == 303
    with SessionLocal() as session:
        assert session.get(RunRecord, run_id) is None


def test_clear_runs_deletes_only_selected_repository(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    repository_id = _make_repository("Clear Runs Repo")

    with SessionLocal() as session:
        run_record = RunRecord(
            repository_id=repository_id, endpoint="/generate", status="completed", created_at=datetime.now(UTC)
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(
            clear_runs(
                request=_fake_request(),
                admin_user="tester",
                _=None,
                repository_id=repository_id,
            )
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/admin/runs?repository_id={repository_id}"
        with SessionLocal() as session:
            assert session.get(RunRecord, run_id) is None
    finally:
        _delete_repository_and_runs(repository_id)


def test_run_detail_renders_for_existing_run(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(run_detail(run_id=run_id, request=_fake_request(), admin_user="tester"))
        assert response.status_code == 200
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_run_detail_renders_docstring_suggestions_preview(monkeypatch, tmp_path):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "suggested_docstrings.json").write_text(
        json.dumps(
            {
                "provider": "github",
                "repo_path": "example/project",
                "branch": "main",
                "suggestions": [
                    {
                        "file_path": "src/app.py",
                        "file_name": "app.py",
                        "function_name": "run",
                        "block_type": "function",
                        "line_number": 10,
                        "language": "python",
                        "generated_docstring": "Runs the app.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/generate",
            status="completed",
            artifact_dir=str(artifact_dir),
            created_at=datetime.now(UTC),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(run_detail(run_id=run_id, request=_fake_request(), admin_user="tester"))
        assert response.status_code == 200
        body = response.body.decode("utf-8")
        assert "Docstring suggestions preview" in body
        assert "src/app.py" in body
        assert "Runs the app." in body
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_run_detail_renders_language_summary(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    languages = [
        {"language": "python", "display_name": "Python", "file_count": 12, "supported": True},
        {"language": "java", "display_name": "Java", "file_count": 3, "supported": False},
    ]
    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/generate",
            status="completed",
            result_payload=json.dumps({"status": "success", "languages_detected": languages}),
            created_at=datetime.now(UTC),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(run_detail(run_id=run_id, request=_fake_request(), admin_user="tester"))
        assert response.status_code == 200
        body = response.body.decode("utf-8")
        assert "Languages detected" in body
        assert "Python" in body
        assert "Java" in body
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_run_detail_raises_404_for_missing_run():
    _assert_raises_http_exception(run_detail(run_id=999_999_999, request=_fake_request(), admin_user="tester"), 404)


def test_run_status_fragment_renders_and_404s(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(run_status_fragment(run_id=run_id, request=_fake_request(), admin_user="tester"))
        assert response.status_code == 200
        assert "window.location.reload()" in response.body.decode("utf-8")
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()

    _assert_raises_http_exception(
        run_status_fragment(run_id=999_999_999, request=_fake_request(), admin_user="tester"), 404
    )


def test_run_status_fragment_omits_reload_script_while_in_progress(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="running", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(run_status_fragment(run_id=run_id, request=_fake_request(), admin_user="tester"))
        assert response.status_code == 200
        assert "window.location.reload()" not in response.body.decode("utf-8")
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_run_detail_full_page_never_includes_reload_script(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(run_detail(run_id=run_id, request=_fake_request(), admin_user="tester"))
        assert response.status_code == 200
        assert "window.location.reload()" not in response.body.decode("utf-8")
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_run_row_fragment_renders_and_404s(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(run_row_fragment(run_id=run_id, request=_fake_request(), admin_user="tester"))
        assert response.status_code == 200
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()

    _assert_raises_http_exception(
        run_row_fragment(run_id=999_999_999, request=_fake_request(), admin_user="tester"), 404
    )


def test_run_log_entries_prioritize_key_logs(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "app.log").write_text("app\n", encoding="utf-8")
    (artifact_dir / "sphinx_build.log").write_text("sphinx\n", encoding="utf-8")
    (artifact_dir / "skipped_autoapi_files.txt").write_text("skip\n", encoding="utf-8")
    (artifact_dir / "notes.json").write_text("{}", encoding="utf-8")

    run = RunRecord(
        artifact_dir=str(artifact_dir),
        log_path=str(artifact_dir / "app.log"),
    )

    entries = run_log_entries(run)

    assert [entry["name"] for entry in entries] == [
        "app.log",
        "sphinx_build.log",
        "skipped_autoapi_files.txt",
    ]


def test_run_log_entries_includes_non_prioritized_log_and_txt_files(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "extra_debug.log").write_text("extra\n", encoding="utf-8")
    (artifact_dir / "notes.json").write_text("{}", encoding="utf-8")

    run = RunRecord(artifact_dir=str(artifact_dir), log_path=None)

    entries = run_log_entries(run)

    assert [entry["name"] for entry in entries] == ["extra_debug.log"]


def test_load_docstring_suggestions_reads_generate_artifact(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "suggested_docstrings.json").write_text(
        json.dumps(
            {
                "provider": "github",
                "repo_path": "example/project",
                "branch": "main",
                "suggestions": [
                    {
                        "file_path": "src/app.py",
                        "file_name": "app.py",
                        "function_name": "run",
                        "block_type": "function",
                        "line_number": 10,
                        "language": "python",
                        "generated_docstring": "Runs the app.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    run = RunRecord(endpoint="/generate", artifact_dir=str(artifact_dir))

    suggestions = load_docstring_suggestions(run)

    assert suggestions == [
        {
            "file_path": "src/app.py",
            "file_name": "app.py",
            "function_name": "run",
            "block_type": "function",
            "line_number": 10,
            "language": "python",
            "generated_docstring": "Runs the app.",
        }
    ]


def test_load_docstring_suggestions_returns_empty_for_non_generate_endpoint(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "suggested_docstrings.json").write_text(
        json.dumps({"suggestions": [{"file_path": "src/app.py"}]}), encoding="utf-8"
    )

    run = RunRecord(endpoint="/publish-pages", artifact_dir=str(artifact_dir))

    assert load_docstring_suggestions(run) == []


def test_load_docstring_suggestions_returns_empty_when_artifact_missing(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    run = RunRecord(endpoint="/generate", artifact_dir=str(artifact_dir))

    assert load_docstring_suggestions(run) == []


def test_load_language_summary_reads_generate_result_payload():
    languages = [
        {"language": "python", "display_name": "Python", "file_count": 12, "supported": True},
        {"language": "java", "display_name": "Java", "file_count": 3, "supported": False},
    ]
    run = RunRecord(
        endpoint="/generate",
        result_payload=json.dumps({"status": "success", "languages_detected": languages}),
    )

    assert load_language_summary(run) == languages


def test_load_language_summary_returns_empty_for_non_generate_endpoint():
    run = RunRecord(
        endpoint="/publish-pages",
        result_payload=json.dumps({"languages_detected": [{"language": "python"}]}),
    )

    assert load_language_summary(run) == []


def test_load_language_summary_returns_empty_when_result_payload_missing():
    run = RunRecord(endpoint="/generate", result_payload=None)

    assert load_language_summary(run) == []


def test_log_snippet_returns_tail_of_file(tmp_path):
    log_path = tmp_path / "app.log"
    log_path.write_text("\n".join(f"line {i}" for i in range(1, 11)) + "\n", encoding="utf-8")

    snippet = log_snippet(str(log_path), limit=3)

    assert snippet == "line 8\nline 9\nline 10\n"


def test_log_snippet_returns_empty_string_when_path_missing():
    assert log_snippet(None) == ""
    assert log_snippet("/nonexistent/path/app.log") == ""


def test_read_artifact_preview_truncates_large_files(tmp_path):
    artifact_path = tmp_path / "sphinx_build.log"
    artifact_path.write_text("x" * 20, encoding="utf-8")

    content, truncated = read_artifact_preview(artifact_path, max_chars=10)

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
                request=_fake_request(),
                admin_user="tester",
            )
        )

        assert response.status_code == 200
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_download_artifact_raises_404_for_missing_run():
    _assert_raises_http_exception(
        download_artifact(
            run_id=999_999_999,
            artifact_name="report.txt",
            request=_fake_request(),
            admin_user="tester",
        ),
        404,
    )


def test_download_artifact_raises_404_for_missing_file(tmp_path):
    artifact_dir = tmp_path / "run1"
    artifact_dir.mkdir()

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
        _assert_raises_http_exception(
            download_artifact(
                run_id=run_id,
                artifact_name="missing.txt",
                request=_fake_request(),
                admin_user="tester",
            ),
            404,
        )
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
        _assert_raises_http_exception(
            download_artifact(
                run_id=run_id,
                artifact_name="../run12/secret.txt",
                request=_fake_request(),
                admin_user="tester",
            ),
            403,
        )
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
        _assert_raises_http_exception(
            download_artifact(
                run_id=run_id,
                artifact_name="report.txt",
                request=_fake_request(),
                admin_user="tester",
            ),
            403,
        )
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
        _assert_raises_http_exception(
            preview_artifact(
                run_id=run_id,
                artifact_name="../run12/secret.txt",
                request=_fake_request(),
                admin_user="tester",
            ),
            403,
        )
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_preview_artifact_raises_404_for_missing_run():
    _assert_raises_http_exception(
        preview_artifact(
            run_id=999_999_999,
            artifact_name="report.txt",
            request=_fake_request(),
            admin_user="tester",
        ),
        404,
    )


def test_preview_artifact_raises_403_for_missing_artifact_dir():
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
        _assert_raises_http_exception(
            preview_artifact(
                run_id=run_id,
                artifact_name="report.txt",
                request=_fake_request(),
                admin_user="tester",
            ),
            403,
        )
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_preview_artifact_renders_content_for_small_file(tmp_path):
    artifact_dir = tmp_path / "run1"
    artifact_dir.mkdir()
    (artifact_dir / "report.txt").write_text("hello <world>", encoding="utf-8")

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
            preview_artifact(
                run_id=run_id,
                artifact_name="report.txt",
                request=_fake_request(),
                admin_user="tester",
            )
        )

        assert response.status_code == 200
        body = bytes(response.body).decode("utf-8")
        assert "hello &lt;world&gt;" in body
        assert "Preview truncated" not in body
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_preview_artifact_shows_truncated_note_for_large_file(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "run1"
    artifact_dir.mkdir()
    (artifact_dir / "report.txt").write_text("x" * 50, encoding="utf-8")
    monkeypatch.setattr("admin.router.read_artifact_preview", lambda path: ("x" * 10, True))

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
            preview_artifact(
                run_id=run_id,
                artifact_name="report.txt",
                request=_fake_request(),
                admin_user="tester",
            )
        )

        assert response.status_code == 200
        assert "Preview truncated" in bytes(response.body).decode("utf-8")
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

    req = build_architecture_generation_request(repository)

    assert req.provider == "github"
    assert req.repo_url == "example/project"
    assert req.token == "secret-token"
    assert req.branch == "main"
    assert req.target_folders == ["src"]
    assert req.output_path == "docs/project/architecture.rst"
    assert req.include_diagrams is True
    assert req.reuse_existing_docs is True


def test_build_pr_request_falls_back_to_repository_defaults(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    repository = RepositoryConfig(
        name="PR Builder Repo",
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

    req = build_pr_request(repository, base_branch=None, suggestion_branch=None, title=None, max_docstrings=50)

    assert req.base_branch == "main"
    assert req.title == "Add suggested docstrings"
    assert req.suggestion_branch is not None
    assert req.suggestion_branch.startswith("autodocs-docstring-suggestions-")


def test_default_suggestion_branch_has_expected_prefix():
    assert default_suggestion_branch().startswith("autodocs-docstring-suggestions-")


def test_safe_request_payload_excludes_token():
    payload = {
        "repo_url": "example/project",
        "token": "secret-token",
        "branch": "main",
    }

    assert safe_request_payload(payload) == {
        "repo_url": "example/project",
        "branch": "main",
    }


def test_database_label_returns_raw_url_for_non_sqlite(monkeypatch):
    monkeypatch.setattr("admin.router.DATABASE_URL", "postgresql://user:pass@host/db")

    assert _database_label() == "postgresql://user:pass@host/db"


def test_json_loads_parses_non_empty_string():
    assert _json_loads('{"a": 1}') == {"a": 1}
    assert _json_loads(None) is None
    assert _json_loads("") is None


def test_queue_payload_with_repository_secret_passes_through_non_token_endpoints():
    payload = {"draft_id": "abc"}

    result = queue_payload_with_repository_secret("/approve-architecture-docs-not-real", payload, None)

    assert result == payload
    assert result is not payload


def test_queue_payload_with_repository_secret_raises_without_repository():
    try:
        queue_payload_with_repository_secret("/generate", {}, None)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422


def test_fmt_duration_formats_none_as_dash():
    assert _fmt_duration(None) == "-"


def test_fmt_duration_formats_sub_second_values():
    assert _fmt_duration(0.5) == "0.50s"


def test_fmt_duration_formats_sub_minute_values():
    assert _fmt_duration(12.3) == "12.3s"


def test_fmt_duration_formats_minutes_and_seconds():
    assert _fmt_duration(125) == "2m 5s"


def test_status_badge_classes_covers_all_states():
    assert "emerald" in _status_badge_classes("completed")
    assert "rose" in _status_badge_classes("failed")
    assert "slate" in _status_badge_classes("cancelled")
    assert "amber" in _status_badge_classes("running")


def test_parse_target_folders_rejects_path_traversal():
    try:
        parse_target_folders("src, ../outside")
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422


def test_validate_provider_rejects_unknown_provider():
    try:
        validate_provider("bitbucket")
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422


def test_validate_repo_form_rejects_missing_name():
    try:
        validate_repo_form("", "github", "example/project", "main", "", "", False, 0.5, 4)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422


def test_validate_repo_form_rejects_missing_repo_url():
    try:
        validate_repo_form("Name", "github", "", "main", "", "", False, 0.5, 4)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422


def test_validate_repo_form_rejects_malformed_github_repo_slug():
    try:
        validate_repo_form(
            "Name",
            "github",
            "Digital-Metabolic-Twin-Centre/-test_documentaion_cobra_toolbox",
            "main",
            "",
            "",
            False,
            0.5,
            4,
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "cannot begin with '-'" in exc.detail


def test_validate_repo_form_rejects_missing_default_branch():
    try:
        validate_repo_form("Name", "github", "example/project", "", "", "", False, 0.5, 4)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422


def test_validate_repo_form_rejects_out_of_range_docstring_threshold():
    try:
        validate_repo_form("Name", "github", "example/project", "main", "", "", False, 1.5, 4)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422


def test_validate_repo_form_rejects_negative_low_content_min_lines():
    try:
        validate_repo_form("Name", "github", "example/project", "main", "", "", False, 0.5, -1)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 422


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
                request=_fake_request(),
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
            assert run_record.request_payload is not None
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
                request=_fake_request(),
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
            assert run_record.request_payload is not None
            stored_payload = json.loads(run_record.request_payload)
            assert "token" not in stored_payload
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.repository_id == repository_id).delete()
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()


def test_trigger_approve_architecture_docs_raises_404_for_missing_run():
    _assert_raises_http_exception(
        trigger_approve_architecture_docs(
            run_id=999_999_999,
            request=_fake_request(),
            admin_user="tester",
            _=None,
            overwrite_existing=False,
            approval_note="",
        ),
        404,
    )


def test_trigger_approve_architecture_docs_requires_generation_run():
    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="completed", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        _assert_raises_http_exception(
            trigger_approve_architecture_docs(
                run_id=run_id,
                request=_fake_request(),
                admin_user="tester",
                _=None,
                overwrite_existing=False,
                approval_note="",
            ),
            422,
        )
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_trigger_approve_architecture_docs_requires_draft_id(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    repository_id = _make_repository("Arch Approval No Draft Repo")

    with SessionLocal() as session:
        run_record = RunRecord(
            repository_id=repository_id,
            endpoint="/generate-architecture-docs",
            status="completed",
            source_branch="main",
            created_at=datetime.now(UTC),
            result_payload=json.dumps({"status": "success"}),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        _assert_raises_http_exception(
            trigger_approve_architecture_docs(
                run_id=run_id,
                request=_fake_request(),
                admin_user="tester",
                _=None,
                overwrite_existing=False,
                approval_note="",
            ),
            422,
        )
    finally:
        _delete_repository_and_runs(repository_id)


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
                request=_fake_request(),
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
            assert run_record.request_payload is not None
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
                request=_fake_request(),
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
            assert retry_record.request_payload is not None
            retry_payload = json.loads(retry_record.request_payload)
            assert "token" not in retry_payload
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.repository_id == repository_id).delete()
            session.query(RepositoryConfig).filter(RepositoryConfig.id == repository_id).delete()
            session.commit()


def test_retry_run_raises_404_for_missing_run():
    _assert_raises_http_exception(
        retry_run(run_id=999_999_999, request=_fake_request(), admin_user="tester", _=None), 404
    )


def test_retry_run_raises_422_when_payload_unavailable():
    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/generate", status="failed", created_at=datetime.now(UTC), request_payload=None
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        _assert_raises_http_exception(
            retry_run(run_id=run_id, request=_fake_request(), admin_user="tester", _=None), 422
        )
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_retry_run_raises_422_for_non_retryable_endpoint():
    # An endpoint outside TOKEN_REQUIRED_ENDPOINTS so `queue_payload_with_repository_secret`
    # passes the payload through untouched and we actually reach retry_run's final `else`.
    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/some-other-endpoint",
            status="failed",
            created_at=datetime.now(UTC),
            request_payload=json.dumps({"provider": "github"}),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        _assert_raises_http_exception(
            retry_run(run_id=run_id, request=_fake_request(), admin_user="tester", _=None), 422
        )
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_retry_run_replays_publish_pages_endpoint(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    captured = {}

    def fake_enqueue_run(run_id, endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload

    monkeypatch.setattr("admin.router.enqueue_run", fake_enqueue_run)
    repository_id = _make_repository("Retry Publish Repo")

    with SessionLocal() as session:
        run_record = RunRecord(
            repository_id=repository_id,
            endpoint="/publish-pages",
            status="failed",
            created_at=datetime.now(UTC),
            request_payload=json.dumps({"repo_url": "example/project", "branch": "main", "low_content_min_lines": 4}),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(retry_run(run_id=run_id, request=_fake_request(), admin_user="tester", _=None))

        assert response.status_code == 303
        assert captured["endpoint"] == "/publish-pages"
        assert captured["payload"]["token"] == "secret-token"
    finally:
        _delete_repository_and_runs(repository_id)


def test_retry_run_replays_suggest_python_docstrings_pr_endpoint(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    captured = {}

    def fake_enqueue_run(run_id, endpoint, payload):
        captured["endpoint"] = endpoint
        captured["payload"] = payload

    monkeypatch.setattr("admin.router.enqueue_run", fake_enqueue_run)
    repository_id = _make_repository("Retry Suggest PR Repo")

    with SessionLocal() as session:
        run_record = RunRecord(
            repository_id=repository_id,
            endpoint="/suggest-python-docstrings-pr",
            status="failed",
            created_at=datetime.now(UTC),
            request_payload=json.dumps(
                {
                    "provider": "github",
                    "repo_url": "example/project",
                    "base_branch": "main",
                    "suggestion_branch": "autodocs/suggestions",
                    "title": "Add suggested docstrings",
                    "max_docstrings": 50,
                }
            ),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(retry_run(run_id=run_id, request=_fake_request(), admin_user="tester", _=None))

        assert response.status_code == 303
        assert captured["endpoint"] == "/suggest-docstrings-pr"
        assert captured["payload"]["token"] == "secret-token"
    finally:
        _delete_repository_and_runs(repository_id)


def test_cancel_run_raises_404_for_unknown_run():
    _assert_raises_http_exception(
        cancel_run(run_id=999_999_999, request=_fake_request(), admin_user="tester", _=None, fragment="redirect"),
        404,
    )


def test_cancel_run_rejects_non_cancellable_outcome():
    with SessionLocal() as session:
        run_record = RunRecord(
            endpoint="/generate",
            status="completed",
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        _assert_raises_http_exception(
            cancel_run(run_id=run_id, request=_fake_request(), admin_user="tester", _=None, fragment="redirect"),
            422,
        )
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_cancel_run_redirects_for_non_htmx_request():
    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="queued", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(
            cancel_run(run_id=run_id, request=_fake_request(), admin_user="tester", _=None, fragment="redirect")
        )

        assert response.status_code == 303
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_cancel_run_returns_status_fragment_for_htmx_request(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="queued", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(
            cancel_run(
                run_id=run_id,
                request=_fake_request(headers={"HX-Request": "true"}),
                admin_user="tester",
                _=None,
                fragment="status",
            )
        )

        assert response.status_code == 200
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_cancel_run_returns_row_fragment_for_htmx_request(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with SessionLocal() as session:
        run_record = RunRecord(endpoint="/generate", status="queued", created_at=datetime.now(UTC))
        session.add(run_record)
        session.commit()
        session.refresh(run_record)
        run_id = run_record.id

    try:
        response = run(
            cancel_run(
                run_id=run_id,
                request=_fake_request(headers={"HX-Request": "true"}),
                admin_user="tester",
                _=None,
                fragment="row",
            )
        )

        assert response.status_code == 200
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()


def test_cancel_run_raises_404_when_run_vanishes_before_htmx_refetch(monkeypatch):
    monkeypatch.setattr("admin.router.request_run_cancellation", lambda run_id: "cancelled")

    _assert_raises_http_exception(
        cancel_run(
            run_id=999_999_999,
            request=_fake_request(headers={"HX-Request": "true"}),
            admin_user="tester",
            _=None,
            fragment="status",
        ),
        404,
    )


def test_preview_artifact_raises_404_for_missing_file(tmp_path):
    artifact_dir = tmp_path / "run1"
    artifact_dir.mkdir()

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
        _assert_raises_http_exception(
            preview_artifact(
                run_id=run_id,
                artifact_name="missing.txt",
                request=_fake_request(),
                admin_user="tester",
            ),
            404,
        )
    finally:
        with SessionLocal() as session:
            session.query(RunRecord).filter(RunRecord.id == run_id).delete()
            session.commit()
