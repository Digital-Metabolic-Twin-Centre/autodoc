import time
from asyncio import run

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from admin.router import _validate_repo_form
from admin.security import (
    _sign_value,
    admin_auth_config_error,
    create_admin_session,
    decrypt_token,
    encrypt_token,
    ensure_csrf_token,
    read_admin_session,
    require_admin,
    set_admin_session,
    validate_admin_credentials,
    verify_csrf,
)


def _request_with_cookies_and_headers(cookies=None, headers=None):
    header_list = [
        (key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()
    ]
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        header_list.append((b"cookie", cookie_header.encode("latin-1")))
    scope = {"type": "http", "method": "POST", "path": "/admin/test", "headers": header_list}
    return Request(scope)


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


def test_set_admin_session_marks_cookie_secure_by_default(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr("admin.security.ADMIN_COOKIE_SECURE", True)
    response = Response()

    set_admin_session(response, "admin")

    assert "secure" in response.headers.get("set-cookie", "").lower()


def test_set_admin_session_respects_disabled_secure_flag(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr("admin.security.ADMIN_COOKIE_SECURE", False)
    response = Response()

    set_admin_session(response, "admin")

    assert "secure" not in response.headers.get("set-cookie", "").lower()


def test_ensure_csrf_token_marks_cookie_secure_by_default(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_COOKIE_SECURE", True)
    scope = {"type": "http", "method": "GET", "path": "/admin", "headers": []}
    request = Request(scope)
    response = Response()

    ensure_csrf_token(request, response)

    assert "secure" in response.headers.get("set-cookie", "").lower()


def test_ensure_csrf_token_respects_disabled_secure_flag(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_COOKIE_SECURE", False)
    scope = {"type": "http", "method": "GET", "path": "/admin", "headers": []}
    request = Request(scope)
    response = Response()

    ensure_csrf_token(request, response)

    assert "secure" not in response.headers.get("set-cookie", "").lower()


def test_admin_auth_config_error_reports_missing_password(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    assert admin_auth_config_error() == "ADMIN_PASSWORD must be configured to sign in to the admin dashboard."


def test_admin_auth_config_error_reports_missing_secret_key(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "secret")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "")

    assert admin_auth_config_error() == "ADMIN_SECRET_KEY must be configured to sign in to the admin dashboard."


def test_encrypt_token_raises_when_secret_key_missing(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "")

    with pytest.raises(HTTPException) as exc_info:
        encrypt_token("some-token")

    assert exc_info.value.status_code == 503


def test_validate_admin_credentials_raises_when_config_incomplete(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_PASSWORD", "")
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")

    with pytest.raises(HTTPException) as exc_info:
        validate_admin_credentials("admin", "whatever")

    assert exc_info.value.status_code == 503


def test_read_admin_session_returns_none_when_secret_key_missing(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "")

    assert read_admin_session("anything.signature") is None


def test_read_admin_session_returns_none_on_signature_mismatch(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    session_value = create_admin_session("admin")
    payload_b64, _signature = session_value.rsplit(".", 1)

    assert read_admin_session(f"{payload_b64}.tampered-signature") is None


def test_read_admin_session_returns_none_on_undecodable_payload(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    bad_payload = "not-valid-base64!!"
    signature = _sign_value(bad_payload)

    assert read_admin_session(f"{bad_payload}.{signature}") is None


def test_read_admin_session_returns_none_for_unknown_username(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr("admin.security.ADMIN_USERNAME", "admin")
    session_value = create_admin_session("someone-else")

    assert read_admin_session(session_value) is None


def test_read_admin_session_returns_none_when_expired(monkeypatch):
    import base64
    import json

    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr("admin.security.ADMIN_USERNAME", "admin")
    monkeypatch.setattr("admin.security.ADMIN_SESSION_MAX_AGE", 60)
    payload = {"username": "admin", "issued_at": int(time.time()) - 3600}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode(
        "utf-8"
    )
    signature = _sign_value(payload_b64)

    assert read_admin_session(f"{payload_b64}.{signature}") is None


def test_require_admin_returns_username_for_valid_session(monkeypatch):
    monkeypatch.setattr("admin.security.ADMIN_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr("admin.security.ADMIN_USERNAME", "admin")
    session_value = create_admin_session("admin")
    request = _request_with_cookies_and_headers(cookies={"autodoc_admin_session": session_value})

    assert require_admin(request) == "admin"


def test_verify_csrf_raises_when_cookie_missing():
    request = _request_with_cookies_and_headers()

    with pytest.raises(HTTPException) as exc_info:
        run(verify_csrf(request, csrf_token=""))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Missing CSRF token."


def test_verify_csrf_raises_when_tokens_mismatch():
    request = _request_with_cookies_and_headers(cookies={"autodoc_csrf": "abc"})

    with pytest.raises(HTTPException) as exc_info:
        run(verify_csrf(request, csrf_token="different"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Invalid CSRF token."


def test_verify_csrf_succeeds_when_form_token_matches_cookie():
    request = _request_with_cookies_and_headers(cookies={"autodoc_csrf": "abc"})

    run(verify_csrf(request, csrf_token="abc"))


def test_verify_csrf_prefers_header_token_over_form_token():
    request = _request_with_cookies_and_headers(
        cookies={"autodoc_csrf": "abc"}, headers={"X-CSRF-Token": "abc"}
    )

    run(verify_csrf(request, csrf_token="wrong-form-value"))


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
