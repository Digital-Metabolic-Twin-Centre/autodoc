import subprocess

from utils.docstring_generation import (
    DEFAULT_OPENAI_MODEL,
    _trim_cli_error,
    format_docstring_for_language,
    generate_docstring,
    resolve_ai_provider,
)


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
