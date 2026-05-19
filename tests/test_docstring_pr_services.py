import json
import os
import subprocess
import textwrap
from contextlib import contextmanager

from services.docstring_pr_services import (
    PatchedPythonFile,
    _load_generated_suggestions,
    _run_ruff_on_patched_files,
    _suggestion_generator,
    create_python_docstring_pull_request,
    patch_python_docstrings,
)


def fake_generator(insertion) -> str:
    return "Generated documentation."


def quoted_generator(insertion) -> str:
    return '"""Retrieve a logger instance with the specified name."""'


def test_patch_python_docstrings_inserts_function_docstring():
    source = textwrap.dedent(
        """
        def add(left, right):
            return left + right
        """
    ).lstrip()

    patched = patch_python_docstrings(source, generator=fake_generator)

    assert patched.inserted[0].name == "add"
    assert '    """Generated documentation."""' in patched.content
    assert "    return left + right" in patched.content


def test_patch_python_docstrings_preserves_existing_docstring():
    source = textwrap.dedent(
        '''
        def documented():
            """Already documented."""
            return True
        '''
    ).lstrip()

    patched = patch_python_docstrings(source, generator=fake_generator)

    assert patched.inserted == []
    assert patched.content == source


def test_patch_python_docstrings_inserts_class_and_method_docstrings():
    source = textwrap.dedent(
        """
        class Thing:
            def name(self):
                return "thing"
        """
    ).lstrip()

    patched = patch_python_docstrings(source, generator=fake_generator, max_docstrings=3)

    assert len(patched.inserted) == 2
    assert '    """Generated documentation."""' in patched.content
    assert '        """Generated documentation."""' in patched.content


def test_patch_python_docstrings_strips_generated_triple_quote_wrapper():
    source = textwrap.dedent(
        """
        def get_logger(name):
            return logging.getLogger(name)
        """
    ).lstrip()

    patched = patch_python_docstrings(source, generator=quoted_generator)

    assert '    """Retrieve a logger instance with the specified name."""' in patched.content
    assert '    """\n    """Retrieve' not in patched.content


def test_patch_python_docstrings_wraps_long_generated_lines():
    source = textwrap.dedent(
        """
        def extract():
            return {}
        """
    ).lstrip()
    long_docstring = (
        "Returns:\n"
        "    dict: A dictionary containing the function code block and the ending line "
        "index, or None if not found."
    )

    patched = patch_python_docstrings(source, generator=lambda insertion: long_docstring)

    assert all(len(line) <= 100 for line in patched.content.splitlines())
    assert "        not found." in patched.content
    assert '\n    \n    """' in patched.content


def test_suggestion_generator_matches_by_name_and_kind():
    source = textwrap.dedent(
        """
        def add(left, right):
            return left + right
        """
    ).lstrip()

    patched = patch_python_docstrings(
        source,
        generator=_suggestion_generator(
            [
                {
                    "function_name": "add",
                    "block_type": "function",
                    "generated_docstring": "Add two values.",
                }
            ]
        ),
    )

    assert '    """Add two values."""' in patched.content


def test_load_generated_suggestions_reads_latest_repo_run_dir(tmp_path, monkeypatch):
    repo_path = "example/project"
    repo_key = "example__project"
    repo_dir = tmp_path / "github" / repo_key
    latest_run_dir = repo_dir / "app_20260429_120000"
    latest_run_dir.mkdir(parents=True)
    (latest_run_dir / "suggested_docstrings.json").write_text(
        json.dumps(
            {
                "provider": "github",
                "repo_path": repo_path,
                "branch": "main",
                "suggestions": [
                    {
                        "file_path": "src/example.py",
                        "function_name": "add",
                        "block_type": "function",
                        "language": "python",
                        "generated_docstring": "Add two values.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))

    suggestions = _load_generated_suggestions(repo_path, "main")

    assert suggestions == {
        "src/example.py": [
            {
                "file_path": "src/example.py",
                "function_name": "add",
                "block_type": "function",
                "language": "python",
                "generated_docstring": "Add two values.",
            }
        ]
    }


def test_load_generated_suggestions_skips_newer_run_dirs_without_suggestion_file(tmp_path, monkeypatch):
    repo_path = "example/project"
    repo_key = "example__project"
    repo_dir = tmp_path / "github" / repo_key
    (repo_dir / "app_20260429_130000").mkdir(parents=True)
    older_run_dir = repo_dir / "app_20260429_120000"
    older_run_dir.mkdir(parents=True)
    (older_run_dir / "suggested_docstrings.json").write_text(
        json.dumps(
            {
                "provider": "github",
                "repo_path": repo_path,
                "branch": "main",
                "suggestions": [
                    {
                        "file_path": "src/example.py",
                        "function_name": "add",
                        "block_type": "function",
                        "language": "python",
                        "generated_docstring": "Add two values.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))

    suggestions = _load_generated_suggestions(repo_path, "main")

    assert suggestions["src/example.py"][0]["generated_docstring"] == "Add two values."


def test_run_ruff_on_patched_files_returns_cleaned_content(monkeypatch):
    cleaned = _run_ruff_on_patched_files(
        {"src/example.py": PatchedPythonFile(content="def run():\n return True\n", inserted=[])}
    )

    assert cleaned["src/example.py"].content == "def run():\n    return True\n"


def test_run_ruff_on_patched_files_gracefully_handles_e402_from_analyzed_project(
    monkeypatch, caplog
):
    calls = {"count": 0}

    def fake_run(command, cwd, capture_output, text, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            target_path = command[-1]
            with open(target_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("def run():\n    return True\n")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                "api/prediction_engines/kinform.py:19:1: E402 Module level import not at top of file\n"
                "Found 1 error.\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("services.docstring_pr_services.subprocess.run", fake_run)

    with caplog.at_level("INFO"):
        cleaned = _run_ruff_on_patched_files(
            {
                "src/example.py": PatchedPythonFile(
                    content="def run():\n return True\n",
                    inserted=[],
                )
            }
        )

    assert cleaned["src/example.py"].content == "def run():\n    return True\n"
    assert "Ruff cleanup skipped import-order lint from the analyzed project" in caplog.text


def test_create_python_docstring_pull_request_returns_no_changes_when_nothing_to_patch(monkeypatch, tmp_path):
    @contextmanager
    def fake_clone(repo_url, token, base_branch, provider):
        """Mock clone_repository context manager."""
        temp_dir = str(tmp_path / "clone")
        os.makedirs(temp_dir, exist_ok=True)

        # Create the Python file that read_file_content_from_local will try to read
        py_file_path = os.path.join(temp_dir, "src/example.py")
        os.makedirs(os.path.dirname(py_file_path), exist_ok=True)
        with open(py_file_path, "w") as f:
            f.write('def documented():\n    """Already documented."""\n    return True\n')

        yield temp_dir

    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {
            "src/example.py": [
                {
                    "function_name": "documented",
                    "block_type": "function",
                    "generated_docstring": "Already documented.",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [{"type": "file", "path": "src/example.py"}],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.clone_repository",
        fake_clone,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.read_file_content_from_local",
        lambda temp_dir, file_path: ('def documented():\n    """Already documented."""\n    return True\n'),
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_content_from_github",
        lambda repo_path, branch, file_path, token: None,  # No files in suggestion_branch yet
    )

    result = create_python_docstring_pull_request(
        "github",
        "example/project",
        "secret",
        "main",
        "autodocs/suggestions",
        "Add suggested docstrings",
    )

    assert result["status"] == "no_changes"
    assert result["pull_request_url"] is None
    assert result["files_changed"] == 0
    assert result["message"] == "No new Python docstring suggestions are available for this branch."
    assert result["detail"] == result["message"]


def test_create_python_docstring_pull_request_returns_no_changes_when_branch_is_current(
    monkeypatch,
):
    source = "def add(left, right):\n    return left + right\n"
    patched_source = 'def add(left, right):\n    """Add two values."""\n    return left + right\n'

    def fake_run_git(command, *args, **kwargs):
        """Mock subprocess.run for git clone."""

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {
            "src/example.py": [
                {
                    "function_name": "add",
                    "block_type": "function",
                    "generated_docstring": "Add two values.",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [{"type": "file", "path": "src/example.py"}],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.subprocess.run",
        fake_run_git,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.read_file_content_from_local",
        lambda temp_dir, file_path: source,  # Return source code from cloned repo
    )

    def fake_fetch_github(repo_path, branch, file_path, token):
        # Return patched content for suggestion_branch to simulate already up-to-date branch
        if branch == "autodocs/suggestions":
            return patched_source
        return None

    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_content_from_github",
        fake_fetch_github,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.ensure_github_branch",
        lambda repo_path, base_branch, suggestion_branch, token: True,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.commit_files_to_github_branch",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("commit_files_to_github_branch should not be called")
        ),
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.create_github_pull_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("create_github_pull_request should not be called")
        ),
    )

    result = create_python_docstring_pull_request(
        "github",
        "example/project",
        "secret",
        "main",
        "autodocs/suggestions",
        "Add suggested docstrings",
    )

    assert result["status"] == "no_changes"
    assert result["pull_request_url"] is None
    assert result["files_changed"] == 0
    assert result["message"] == "No new Python docstring suggestions are available for this branch."
    assert result["detail"] == result["message"]
