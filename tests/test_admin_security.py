import pytest
from fastapi import HTTPException
from starlette.requests import Request

from admin.router import _validate_repo_form
from admin.security import (
    create_admin_session,
    decrypt_token,
    encrypt_token,
    read_admin_session,
    require_admin,
    validate_admin_credentials,
)


def test_validate_admin_credentials_rejects_invalid_credentials(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "secret")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with pytest.raises(ValueError):
        validate_admin_credentials("admin", "wrong")


def test_token_encryption_round_trip(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    encrypted = encrypt_token("super-secret-token")

    assert encrypted != "super-secret-token"
    assert decrypt_token(encrypted) == "super-secret-token"


def test_admin_session_round_trip(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    session_value = create_admin_session("admin")

    assert read_admin_session(session_value) == "admin"


def test_require_admin_redirects_when_session_missing(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    scope = {"type": "http", "method": "GET", "path": "/admin", "headers": []}
    request = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        require_admin(request)

    assert exc_info.value.status_code == 303
    assert exc_info.value.headers == {"Location": "/admin/login"}


def test_validate_repo_form_normalizes_target_folders():
    result = _validate_repo_form(
        name="Example Repo",
        provider="github",
        repo_url="https://github.com/example/project",
        default_branch="main",
        target_folders="src, tests\nscripts",
        preferred_model="gpt-4o-mini",
        reuse_doc=True,
        docstring_threshold=0.5,
        low_content_min_lines=4,
    )

    assert result["repo_path"] == "example/project"
    assert result["target_folders"] == ["src", "tests", "scripts"]
