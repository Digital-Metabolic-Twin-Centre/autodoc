import pytest

from utils.redaction import redact_secrets


def test_redact_secrets_strips_github_clone_url_credentials():
    text = "fatal: unable to access 'https://x-access-token:ghp_abcdefghijklmnopqrstuvwxyz123456@github.com/o/r.git/'"

    redacted = redact_secrets(text)

    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "https://***:***@github.com/o/r.git/" in redacted


def test_redact_secrets_strips_gitlab_clone_url_credentials():
    text = "remote: HTTP Basic: Access denied. fatal: unable to access 'https://oauth2:glpat-abcdefghijklmnop@gitlab.com/o/r.git/'"

    redacted = redact_secrets(text)

    assert "glpat-abcdefghijklmnop" not in redacted
    assert "https://***:***@gitlab.com/o/r.git/" in redacted


def test_redact_secrets_strips_bare_known_token_formats():
    text = "token ghp_abcdefghijklmnopqrstuvwxyz123456 rejected"

    redacted = redact_secrets(text)

    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "***REDACTED-TOKEN***" in redacted


def test_redact_secrets_passes_through_text_without_credentials():
    text = "Repository 'example/project' not found."

    assert redact_secrets(text) == text


def test_redact_secrets_handles_none_and_empty_string():
    assert redact_secrets(None) is None
    assert redact_secrets("") == ""


def test_redact_secrets_strips_fine_grained_github_pat():
    text = "token github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz rejected"

    redacted = redact_secrets(text)

    assert "github_pat_11ABCDEFG0123456789" not in redacted
    assert "***REDACTED-TOKEN***" in redacted


@pytest.mark.parametrize(
    "prefix",
    ["glpat", "gldt", "glrt", "glcbt", "glptt", "glft", "glimt", "glagent", "glsoat", "gloas"],
)
def test_redact_secrets_strips_gitlab_token_family(prefix):
    text = f"token {prefix}-abcdefghijklmnop rejected"

    redacted = redact_secrets(text)

    assert f"{prefix}-abcdefghijklmnop" not in redacted
    assert "***REDACTED-TOKEN***" in redacted


def test_redact_secrets_strips_openai_api_key():
    text = "openai.AuthenticationError: Incorrect API key provided: sk-proj-abcdefghijklmnopqrstuvwx"

    redacted = redact_secrets(text)

    assert "sk-proj-abcdefghijklmnopqrstuvwx" not in redacted
    assert "***REDACTED-TOKEN***" in redacted


def test_redact_secrets_strips_bearer_auth_header_value():
    text = "GitHub rejected request: Authorization: Bearer ghs_abcXYZ123.token~value invalid"

    redacted = redact_secrets(text)

    assert "ghs_abcXYZ123.token~value" not in redacted
    assert "Bearer ***REDACTED-TOKEN***" in redacted


def test_redact_secrets_strips_basic_auth_header_value():
    text = "request failed: Authorization: Basic dXNlcjpwYXNzd29yZA=="

    redacted = redact_secrets(text)

    assert "dXNlcjpwYXNzd29yZA==" not in redacted
    assert "Basic ***REDACTED-TOKEN***" in redacted
