from pathlib import Path

from utils.docstring_validation import (
    analyze_docstring_in_blocks,
    analyze_docstring_in_module,
)


def test_analyze_docstring_in_module_returns_python_module_docstring():
    content = '"""Module summary."""\n\n\ndef run():\n    return True\n'

    result = analyze_docstring_in_module(content, "python")

    assert result == "Module summary."


def test_analyze_docstring_in_blocks_flags_missing_python_docstrings(monkeypatch):
    monkeypatch.setattr(
        "utils.docstring_validation.generate_docstring_with_openai",
        lambda code, language, model=None: None,
    )

    blocks = [
        "# --- Code Block starts at line 1 ---\n"
        "def run_task():\n"
        "    return True\n"
        "# --- Code Block ends at line 2 ---"
    ]

    result = analyze_docstring_in_blocks(
        blocks,
        file_name="worker.py",
        file_path="worker.py",
        language="python",
    )

    assert result["blocks_without_docstring"] == 1
    assert result["docstring_analysis"][0]["function_name"] == "run_task"
    assert result["docstring_analysis"][0]["missing_docstring"] is True


def test_analyze_docstring_in_blocks_detects_existing_python_docstrings():
    blocks = [
        "# --- Code Block starts at line 1 ---\n"
        'def run_task():\n    """Run the task."""\n    return True\n'
        "# --- Code Block ends at line 3 ---"
    ]

    result = analyze_docstring_in_blocks(
        blocks,
        file_name="worker.py",
        file_path="worker.py",
        language="python",
    )

    assert result["blocks_with_docstring"] == 1
    assert result["docstring_analysis"][0]["docstring_content"] == "Run the task."


def test_analyze_docstring_in_blocks_writes_suggestions_to_repo_scoped_file(
    monkeypatch, tmp_path
):
    captured = {}

    monkeypatch.setattr(
        "utils.docstring_validation.generate_docstring_with_openai",
        lambda code, language, model=None: (
            captured.update({"model": model}) or "Run the task."
        ),
    )
    suggested_file = tmp_path / "logs" / "github" / "owner__repo" / "suggested_docstring.txt"
    suggested_file.parent.mkdir(parents=True, exist_ok=True)

    blocks = [
        "# --- Code Block starts at line 1 ---\n"
        "def run_task():\n"
        "    return True\n"
        "# --- Code Block ends at line 2 ---"
    ]

    analyze_docstring_in_blocks(
        blocks,
        file_name="worker.py",
        file_path="worker.py",
        language="python",
        suggested_file=str(suggested_file),
        model="gpt-4.1-mini",
    )

    content = suggested_file.read_text(encoding="utf-8")
    assert captured["model"] == "gpt-4.1-mini"
    assert "File: worker.py, Path: worker.py, Function: run_task, Line: 1" in content
    assert "Run the task." in content
