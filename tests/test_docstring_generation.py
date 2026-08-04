import subprocess
from types import SimpleNamespace

import httpx
import openai
import pytest

from utils.docstring_generation import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS,
    _openai_request_timeout_seconds,
    _trim_cli_error,
    format_docstring_for_language,
    generate_docstring,
    resolve_ai_provider,
)


def _fake_openai_request():
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _fake_openai_response(status_code):
    return httpx.Response(status_code, request=_fake_openai_request())


def _fake_completion_response(docstring="Run the task."):
    message = SimpleNamespace(content=f'{{"docstring": "{docstring}"}}')
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _configure_openai_provider(monkeypatch):
    """Force generate_docstring down the OpenAI SDK path (not the codex/claude CLI path)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("AUTODOC_AI_PROVIDER", "openai")
    monkeypatch.delenv("AUTODOC_AI_MODEL", raising=False)


def test_format_python_docstring_strips_triple_quote_wrapper():
    formatted = format_docstring_for_language(
        '"""Create or update a file.\n\nArgs:\n    path (str): File path."""',
        "python",
    )

    assert formatted.startswith('    """\n    Create or update a file.')
    assert '    """\n    """Create' not in formatted
    assert formatted.endswith('    """')


def test_format_python_docstring_keeps_plain_docstring_content():
    formatted = format_docstring_for_language("Create or update a file.", "python")

    assert formatted == '    """\n    Create or update a file.\n    """'


def test_format_python_docstring_wraps_long_lines():
    formatted = format_docstring_for_language(
        "Returns:\n"
        "    dict: A dictionary containing the function code block and the ending line "
        "index, or None if not found.",
        "python",
    )

    assert all(len(line) <= 100 for line in formatted.splitlines())
    assert "        not found." in formatted
    assert formatted.endswith('\n    """')
    assert '\n\n    """' in formatted


def test_format_julia_docstring_uses_unindented_triple_quotes():
    formatted = format_docstring_for_language("Adds one to value.", "julia")

    assert formatted == '"""\nAdds one to value.\n"""'


def test_resolve_ai_provider_uses_codex_when_openai_key_is_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AUTODOC_AI_PROVIDER", raising=False)
    monkeypatch.delenv("AUTODOC_AI_MODEL", raising=False)
    monkeypatch.delenv("AUTODOC_AI_CLI_PROVIDER", raising=False)

    provider, model = resolve_ai_provider(DEFAULT_OPENAI_MODEL)

    assert provider == "codex"
    assert model is None


def test_resolve_ai_provider_allows_model_prefix(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.delenv("AUTODOC_AI_PROVIDER", raising=False)
    monkeypatch.delenv("AUTODOC_AI_MODEL", raising=False)

    provider, model = resolve_ai_provider("claude:sonnet")

    assert provider == "claude"
    assert model == "sonnet"


def test_generate_docstring_uses_claude_cli(monkeypatch):
    captured = {}

    def fake_run(command, input, capture_output, text, timeout):
        captured["command"] = command
        captured["input"] = input
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"docstring": "Run the task."}',
            stderr="",
        )

    monkeypatch.setenv("AUTODOC_AI_PROVIDER", "claude")
    monkeypatch.setenv("AUTODOC_AI_CLI_TIMEOUT", "10")
    monkeypatch.delenv("AUTODOC_AI_MODEL", raising=False)
    monkeypatch.setattr("utils.docstring_generation.subprocess.run", fake_run)

    result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result == "Run the task."
    assert captured["command"][:2] == ["claude", "-p"]
    assert "--model" not in captured["command"]
    assert "Generate a concise docstring" in captured["input"]
    assert captured["timeout"] == 10


def test_generate_docstring_uses_codex_cli_with_prefixed_model(monkeypatch):
    captured = {}

    def fake_run(command, input, capture_output, text, timeout):
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='Some preface\n{"docstring": "Run the task."}\n',
            stderr="",
        )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AUTODOC_AI_PROVIDER", raising=False)
    monkeypatch.delenv("AUTODOC_AI_MODEL", raising=False)
    monkeypatch.setattr("utils.docstring_generation.subprocess.run", fake_run)

    result = generate_docstring("def run_task():\n    return True\n", "python", model="codex:gpt-5")

    assert result == "Run the task."
    assert captured["command"][:2] == ["codex", "exec"]
    assert captured["command"][-3:] == ["--model", "gpt-5", "-"]


def test_generate_docstring_does_not_pass_unprefixed_saved_model_to_cli(monkeypatch):
    captured = {}

    def fake_run(command, input, capture_output, text, timeout):
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"docstring": "Run the task."}',
            stderr="",
        )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AUTODOC_AI_PROVIDER", "codex")
    monkeypatch.delenv("AUTODOC_AI_MODEL", raising=False)
    monkeypatch.setattr("utils.docstring_generation.subprocess.run", fake_run)

    result = generate_docstring("def run_task():\n    return True\n", "python", model="GPT-5.5")

    assert result == "Run the task."
    assert captured["command"] == ["codex", "exec", "--skip-git-repo-check", "-"]


def test_openai_request_timeout_seconds_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("AUTODOC_OPENAI_TIMEOUT", raising=False)

    assert _openai_request_timeout_seconds() == DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS


def test_openai_request_timeout_seconds_reads_env_override(monkeypatch):
    monkeypatch.setenv("AUTODOC_OPENAI_TIMEOUT", "15")

    assert _openai_request_timeout_seconds() == 15


def test_openai_request_timeout_seconds_falls_back_on_invalid_value(monkeypatch, caplog):
    monkeypatch.setenv("AUTODOC_OPENAI_TIMEOUT", "not-a-number")

    with caplog.at_level("WARNING"):
        timeout = _openai_request_timeout_seconds()

    assert timeout == DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS
    assert "Invalid AUTODOC_OPENAI_TIMEOUT" in caplog.text


def test_generate_docstring_passes_configured_timeout_to_openai_call(monkeypatch):
    monkeypatch.setenv("AUTODOC_OPENAI_TIMEOUT", "5")
    _configure_openai_provider(monkeypatch)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_completion_response()

    monkeypatch.setattr("utils.docstring_generation.openai.chat.completions.create", fake_create)

    result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result == "Run the task."
    assert captured["timeout"] == 5


def test_generate_docstring_returns_none_and_logs_on_authentication_error(monkeypatch, caplog):
    _configure_openai_provider(monkeypatch)

    def fake_create(**kwargs):
        raise openai.AuthenticationError(
            "Incorrect API key provided", response=_fake_openai_response(401), body=None
        )

    monkeypatch.setattr("utils.docstring_generation.openai.chat.completions.create", fake_create)

    with caplog.at_level("ERROR"):
        result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result is None
    assert "authentication failed" in caplog.text.lower()


def test_generate_docstring_returns_none_and_logs_on_rate_limit_error(monkeypatch, caplog):
    _configure_openai_provider(monkeypatch)

    def fake_create(**kwargs):
        raise openai.RateLimitError("Rate limit exceeded", response=_fake_openai_response(429), body=None)

    monkeypatch.setattr("utils.docstring_generation.openai.chat.completions.create", fake_create)

    with caplog.at_level("WARNING"):
        result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result is None
    assert "rate limit" in caplog.text.lower()


def test_generate_docstring_returns_none_and_logs_on_timeout_error(monkeypatch, caplog):
    _configure_openai_provider(monkeypatch)

    def fake_create(**kwargs):
        raise openai.APITimeoutError(request=_fake_openai_request())

    monkeypatch.setattr("utils.docstring_generation.openai.chat.completions.create", fake_create)

    with caplog.at_level("WARNING"):
        result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result is None
    assert "timed out" in caplog.text.lower()


def test_generate_docstring_returns_none_and_logs_on_connection_error(monkeypatch, caplog):
    _configure_openai_provider(monkeypatch)

    def fake_create(**kwargs):
        raise openai.APIConnectionError(message="Connection error.", request=_fake_openai_request())

    monkeypatch.setattr("utils.docstring_generation.openai.chat.completions.create", fake_create)

    with caplog.at_level("WARNING"):
        result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result is None
    assert "could not reach openai" in caplog.text.lower()


def test_generate_docstring_returns_none_and_logs_on_generic_api_error(monkeypatch, caplog):
    _configure_openai_provider(monkeypatch)

    def fake_create(**kwargs):
        raise openai.APIError("Something went wrong", request=_fake_openai_request(), body=None)

    monkeypatch.setattr("utils.docstring_generation.openai.chat.completions.create", fake_create)

    with caplog.at_level("ERROR"):
        result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result is None
    assert "openai api error" in caplog.text.lower()


def test_generate_docstring_returns_none_and_logs_distinctly_on_unparseable_response(monkeypatch, caplog):
    _configure_openai_provider(monkeypatch)

    def fake_create(**kwargs):
        message = SimpleNamespace(content="not json at all")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("utils.docstring_generation.openai.chat.completions.create", fake_create)

    with caplog.at_level("ERROR"):
        result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result is None
    assert "failed to parse" in caplog.text.lower()


def test_generate_docstring_returns_none_when_no_choices_in_response(monkeypatch, caplog):
    _configure_openai_provider(monkeypatch)

    monkeypatch.setattr(
        "utils.docstring_generation.openai.chat.completions.create",
        lambda **kwargs: SimpleNamespace(choices=[]),
    )

    with caplog.at_level("WARNING"):
        result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result is None
    assert "no response from openai" in caplog.text.lower()


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: openai.AuthenticationError("bad key", response=_fake_openai_response(401), body=None),
        lambda: openai.RateLimitError("slow down", response=_fake_openai_response(429), body=None),
        lambda: openai.APITimeoutError(request=_fake_openai_request()),
        lambda: openai.APIConnectionError(message="down", request=_fake_openai_request()),
        lambda: openai.APIError("broken", request=_fake_openai_request(), body=None),
    ],
)
def test_generate_docstring_never_raises_for_openai_failures(monkeypatch, exc_factory):
    """generate_docstring's Optional[str] contract means callers rely on it never raising."""
    _configure_openai_provider(monkeypatch)

    def fake_create(**kwargs):
        raise exc_factory()

    monkeypatch.setattr("utils.docstring_generation.openai.chat.completions.create", fake_create)

    result = generate_docstring("def run_task():\n    return True\n", "python")

    assert result is None


def test_trim_cli_error_omits_prompt_metadata_and_truncates_source():
    stderr = "\n".join(
        [
            "OpenAI Codex v0.142.5",
            "--------",
            "workdir: /repo",
            "model: GPT-5.5",
            "provider: openai",
            "user",
            "def secret_function():",
            "    return 'source code'",
            "ERROR: unsupported model",
        ]
    )

    cleaned = _trim_cli_error(stderr, limit=50)

    assert "workdir:" not in cleaned
    assert "model:" not in cleaned
    assert "provider:" not in cleaned
    assert "def secret_function" not in cleaned
    assert "ERROR: unsupported model" in cleaned
