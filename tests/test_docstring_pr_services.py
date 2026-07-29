import json
import os
import subprocess
import textwrap
from contextlib import contextmanager

import pytest

from services.docstring_pr_services import (
    DocstringInsertion,
    DocstringPullRequestError,
    PatchedPythonFile,
    _build_pull_request_body,
    _find_matching_open_pull_request,
    _format_python_docstring,
    _load_generated_suggestions,
    _run_ruff_on_patched_files,
    _suggestion_generator,
    create_python_docstring_pull_request,
    patch_python_docstrings,
)
from utils.git_utils import GitHubApiError, RepositoryAccessError


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


def test_format_python_docstring_preserves_blank_lines_between_paragraphs():
    formatted = _format_python_docstring("Summary line.\n\nMore details here.", "    ")

    assert "" in [line.strip() for line in formatted]


def test_format_python_docstring_falls_back_to_todo_when_empty():
    formatted = _format_python_docstring("   ", "    ")

    assert formatted == ['    """TODO: Add documentation."""']


def test_patch_python_docstrings_handles_async_function():
    source = textwrap.dedent(
        """
        async def fetch():
            return await other()
        """
    ).lstrip()

    patched = patch_python_docstrings(source, generator=fake_generator)

    assert patched.inserted[0].kind == "async_function"
    assert '    """Generated documentation."""' in patched.content


def test_patch_python_docstrings_stops_once_budget_exhausted():
    source = textwrap.dedent(
        """
        def first():
            return 1


        def second():
            return 2
        """
    ).lstrip()
    calls = []

    def counting_generator(insertion):
        calls.append(insertion.name)
        return "Generated documentation."

    patched = patch_python_docstrings(source, generator=counting_generator, max_docstrings=1)

    assert len(patched.inserted) == 1
    assert calls == ["second"]


def test_patch_python_docstrings_skips_insertions_when_generator_returns_none():
    source = textwrap.dedent(
        """
        def undocumented():
            return 1
        """
    ).lstrip()

    patched = patch_python_docstrings(source, generator=lambda insertion: None)

    assert patched.inserted == []
    assert patched.content == source


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


def test_suggestion_generator_skips_used_and_non_matching_entries():
    suggestions = [
        {"function_name": "foo", "block_type": "class", "generated_docstring": "A"},
        {"function_name": "bar", "block_type": "function", "generated_docstring": "B"},
    ]
    generate = _suggestion_generator(suggestions)
    bar_insertion = DocstringInsertion(
        name="bar", kind="function", line_number=1, insert_index=0, indent="    ", code=""
    )

    first_result = generate(bar_insertion)
    second_result = generate(bar_insertion)

    assert first_result == "B"
    assert second_result is None


def test_suggestion_generator_returns_none_when_kind_does_not_match():
    suggestions = [{"function_name": "bar", "block_type": "class", "generated_docstring": "C"}]
    generate = _suggestion_generator(suggestions)
    bar_function_insertion = DocstringInsertion(
        name="bar", kind="function", line_number=1, insert_index=0, indent="    ", code=""
    )

    assert generate(bar_function_insertion) is None


def test_build_pull_request_body_summarizes_changed_files():
    files_changed = {
        "src/example.py": PatchedPythonFile(
            content="",
            inserted=[
                DocstringInsertion(name="add", kind="function", line_number=1, insert_index=0, indent="", code="")
            ],
        )
    }

    body = _build_pull_request_body("main", files_changed)

    assert "Adds 1 generated Python docstring suggestion(s)" in body
    assert "`src/example.py`: 1 docstring(s)" in body
    assert "Base branch: `main`" in body


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


def test_load_generated_suggestions_raises_when_nothing_generated_yet(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))

    with pytest.raises(DocstringPullRequestError, match="No generated docstring suggestions found"):
        _load_generated_suggestions("example/project", "main")


def test_load_generated_suggestions_raises_when_repo_or_branch_mismatch(tmp_path, monkeypatch):
    repo_dir = tmp_path / "github" / "example__project"
    run_dir = repo_dir / "app_20260429_120000"
    run_dir.mkdir(parents=True)
    (run_dir / "suggested_docstrings.json").write_text(
        json.dumps({"provider": "github", "repo_path": "other/project", "branch": "main", "suggestions": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))

    with pytest.raises(DocstringPullRequestError, match="do not match this repo/branch"):
        _load_generated_suggestions("example/project", "main")


def test_load_generated_suggestions_skips_non_python_suggestions(tmp_path, monkeypatch):
    repo_dir = tmp_path / "github" / "example__project"
    run_dir = repo_dir / "app_20260429_120000"
    run_dir.mkdir(parents=True)
    (run_dir / "suggested_docstrings.json").write_text(
        json.dumps(
            {
                "provider": "github",
                "repo_path": "example/project",
                "branch": "main",
                "suggestions": [
                    {
                        "file_path": "src/example.js",
                        "function_name": "add",
                        "block_type": "function",
                        "language": "javascript",
                        "generated_docstring": "Add two values.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))

    suggestions = _load_generated_suggestions("example/project", "main")

    assert suggestions == {}


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


def test_run_ruff_on_patched_files_returns_empty_dict_unchanged():
    assert _run_ruff_on_patched_files({}) == {}


def test_run_ruff_on_patched_files_returns_cleaned_content(monkeypatch):
    cleaned = _run_ruff_on_patched_files(
        {"src/example.py": PatchedPythonFile(content="def run():\n return True\n", inserted=[])}
    )

    assert cleaned["src/example.py"].content == "def run():\n    return True\n"


def test_run_ruff_on_patched_files_gracefully_handles_e402_from_analyzed_project(monkeypatch, caplog):
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
                "api/prediction_engines/kinform.py:19:1: E402 Module level import not at top of file\nFound 1 error.\n"
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


def test_run_ruff_on_patched_files_handles_non_e402_lint_failure(monkeypatch, caplog):
    def fake_run(command, cwd, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="src/example.py:1:1: F821 undefined name 'x'\nFound 1 error.\n",
            stderr="",
        )

    monkeypatch.setattr("services.docstring_pr_services.subprocess.run", fake_run)

    with caplog.at_level("WARNING"):
        cleaned = _run_ruff_on_patched_files(
            {"src/example.py": PatchedPythonFile(content="x\n", inserted=[])}
        )

    assert cleaned["src/example.py"].content == "x\n"
    assert "Ruff cleanup skipped due to non-docstring lint in the analyzed project" in caplog.text


def test_run_ruff_on_patched_files_handles_empty_output_on_failure(monkeypatch, caplog):
    def fake_run(command, cwd, capture_output, text, timeout):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr("services.docstring_pr_services.subprocess.run", fake_run)

    with caplog.at_level("WARNING"):
        cleaned = _run_ruff_on_patched_files(
            {"src/example.py": PatchedPythonFile(content="x\n", inserted=[])}
        )

    assert cleaned["src/example.py"].content == "x\n"
    assert "unknown Ruff error" in caplog.text


def test_find_matching_open_pull_request_returns_none_when_no_patched_files():
    assert _find_matching_open_pull_request("example/project", "main", {}, "token") is None


def test_find_matching_open_pull_request_skips_pull_requests_missing_ref(monkeypatch):
    monkeypatch.setattr(
        "services.docstring_pr_services.list_open_github_pull_requests",
        lambda repo_path, base_branch, token: [{"number": None, "head": {}}],
    )

    result = _find_matching_open_pull_request(
        "example/project", "main", {"src/example.py": PatchedPythonFile(content="x", inserted=[])}, "token"
    )

    assert result is None


def test_find_matching_open_pull_request_skips_when_changed_paths_differ(monkeypatch):
    monkeypatch.setattr(
        "services.docstring_pr_services.list_open_github_pull_requests",
        lambda repo_path, base_branch, token: [
            {"number": 1, "html_url": "https://example/pr/1", "head": {"ref": "suggestions"}}
        ],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.list_github_pull_request_files",
        lambda repo_path, pull_number, token: [{"filename": "src/other.py"}],
    )

    result = _find_matching_open_pull_request(
        "example/project", "main", {"src/example.py": PatchedPythonFile(content="x", inserted=[])}, "token"
    )

    assert result is None


def test_find_matching_open_pull_request_skips_when_content_differs(monkeypatch):
    monkeypatch.setattr(
        "services.docstring_pr_services.list_open_github_pull_requests",
        lambda repo_path, base_branch, token: [
            {"number": 1, "html_url": "https://example/pr/1", "head": {"ref": "suggestions"}}
        ],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.list_github_pull_request_files",
        lambda repo_path, pull_number, token: [{"filename": "src/example.py"}],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_content_from_github",
        lambda repo_path, branch, file_path, token: "different content",
    )

    result = _find_matching_open_pull_request(
        "example/project", "main", {"src/example.py": PatchedPythonFile(content="x", inserted=[])}, "token"
    )

    assert result is None


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


def test_create_python_docstring_pull_request_returns_no_changes_when_matching_pr_already_exists(
    monkeypatch,
):
    source = "def add(left, right):\n    return left + right\n"
    patched_source = 'def add(left, right):\n    """Add two values."""\n    return left + right\n'

    @contextmanager
    def fake_clone(repo_url, token, base_branch, provider):
        yield "/tmp/fake-clone"

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
    monkeypatch.setattr("services.docstring_pr_services.clone_repository", fake_clone)
    monkeypatch.setattr(
        "services.docstring_pr_services.read_file_content_from_local",
        lambda temp_dir, file_path: source,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.list_open_github_pull_requests",
        lambda repo_path, base_branch, token: [
            {
                "number": 17,
                "html_url": "https://github.com/example/project/pull/17",
                "head": {"ref": "autodocs-docstring-suggestions-20260522-1000"},
            }
        ],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.list_github_pull_request_files",
        lambda repo_path, pull_number, token: [{"filename": "src/example.py"}],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_content_from_github",
        lambda repo_path, branch, file_path, token: patched_source,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.ensure_github_branch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ensure_github_branch should not be called")),
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
        "autodocs-docstring-suggestions-20260522-1100",
        "Add suggested docstrings",
    )

    assert result["status"] == "no_changes"
    assert result["pull_request_url"] is None
    assert result["existing_pull_request_url"] == "https://github.com/example/project/pull/17"
    assert result["message"] == "A matching Python docstring suggestion pull request is already open for this branch."


def test_create_python_docstring_pull_request_rejects_non_github_provider():
    with pytest.raises(DocstringPullRequestError, match="currently support GitHub only"):
        create_python_docstring_pull_request(
            "gitlab", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )


def test_create_python_docstring_pull_request_raises_when_no_suggestions(monkeypatch):
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {},
    )

    with pytest.raises(DocstringPullRequestError, match="No generated Python docstring suggestions"):
        create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )


@contextmanager
def _fake_clone(repo_url, token, base_branch, provider):
    yield "/tmp/fake-clone"


def test_create_python_docstring_pull_request_raises_when_no_python_files(monkeypatch):
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {"src/example.py": [{}]},
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [{"type": "file", "path": "README.md"}],
    )
    monkeypatch.setattr("services.docstring_pr_services.clone_repository", _fake_clone)

    with pytest.raises(DocstringPullRequestError, match="No Python files found"):
        create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )


def test_create_python_docstring_pull_request_stops_when_budget_exhausted(monkeypatch):
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {
            "src/example.py": [
                {"function_name": "add", "block_type": "function", "generated_docstring": "Add two values."}
            ]
        },
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [{"type": "file", "path": "src/example.py"}],
    )
    monkeypatch.setattr("services.docstring_pr_services.clone_repository", _fake_clone)
    monkeypatch.setattr(
        "services.docstring_pr_services.read_file_content_from_local",
        lambda temp_dir, file_path: (_ for _ in ()).throw(AssertionError("should not read when budget is 0")),
    )

    result = create_python_docstring_pull_request(
        "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings",
        max_docstrings=0,
    )

    assert result["status"] == "no_changes"


def test_create_python_docstring_pull_request_skips_empty_and_unmatched_files(monkeypatch):
    _setup_happy_path(monkeypatch, fetch_content_from_github=lambda repo_path, branch, file_path, token: None)
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {
            "src/has_suggestions.py": [
                {"function_name": "add", "block_type": "function", "generated_docstring": "Add two values."}
            ]
        },
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [
            {"type": "file", "path": "src/empty.py"},
            {"type": "file", "path": "src/no_suggestions.py"},
            {"type": "file", "path": "src/has_suggestions.py"},
        ],
    )

    def fake_read(temp_dir, file_path):
        if file_path == "src/empty.py":
            return ""
        if file_path == "src/no_suggestions.py":
            return "def unrelated():\n    return 1\n"
        return "def add(left, right):\n    return left + right\n"

    monkeypatch.setattr("services.docstring_pr_services.read_file_content_from_local", fake_read)

    result = create_python_docstring_pull_request(
        "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
    )

    # Only src/has_suggestions.py had matching suggestions; the others were skipped via `continue`.
    assert result["status"] == "success"
    assert result["changed_files"] == ["src/has_suggestions.py"]


def test_create_python_docstring_pull_request_skips_file_with_syntax_error(monkeypatch, caplog):
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {
            "src/broken.py": [
                {"function_name": "add", "block_type": "function", "generated_docstring": "Add two values."}
            ]
        },
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [{"type": "file", "path": "src/broken.py"}],
    )
    monkeypatch.setattr("services.docstring_pr_services.clone_repository", _fake_clone)
    monkeypatch.setattr(
        "services.docstring_pr_services.read_file_content_from_local",
        lambda temp_dir, file_path: "def broken(:\n    pass\n",
    )

    with caplog.at_level("WARNING"):
        result = create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )

    assert result["status"] == "no_changes"
    assert "Python parsing failed" in caplog.text


def test_create_python_docstring_pull_request_returns_no_changes_when_ruff_reverts_all_changes(monkeypatch):
    source = "def add(left, right):\n    return left + right\n"
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {
            "src/example.py": [
                {"function_name": "add", "block_type": "function", "generated_docstring": "Add two values."}
            ]
        },
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [{"type": "file", "path": "src/example.py"}],
    )
    monkeypatch.setattr("services.docstring_pr_services.clone_repository", _fake_clone)
    monkeypatch.setattr(
        "services.docstring_pr_services.read_file_content_from_local",
        lambda temp_dir, file_path: source,
    )

    def fake_run_ruff_on_patched_files(patched_files):
        return {
            path: PatchedPythonFile(content=source, inserted=patched_file.inserted)
            for path, patched_file in patched_files.items()
        }

    # Simulate ruff reformatting reverting the patch back to the original source exactly.
    monkeypatch.setattr(
        "services.docstring_pr_services._run_ruff_on_patched_files",
        fake_run_ruff_on_patched_files,
    )

    result = create_python_docstring_pull_request(
        "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
    )

    assert result["status"] == "no_changes"


def test_create_python_docstring_pull_request_raises_when_branch_not_ready(monkeypatch):
    source = "def add(left, right):\n    return left + right\n"
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {
            "src/example.py": [
                {"function_name": "add", "block_type": "function", "generated_docstring": "Add two values."}
            ]
        },
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [{"type": "file", "path": "src/example.py"}],
    )
    monkeypatch.setattr("services.docstring_pr_services.clone_repository", _fake_clone)
    monkeypatch.setattr(
        "services.docstring_pr_services.read_file_content_from_local",
        lambda temp_dir, file_path: source,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services._run_ruff_on_patched_files", lambda patched_files: patched_files
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.list_open_github_pull_requests",
        lambda repo_path, base_branch, token: [],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.ensure_github_branch",
        lambda repo_path, base_branch, suggestion_branch, token: False,
    )

    with pytest.raises(DocstringPullRequestError, match="Could not create or access the suggestion branch"):
        create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )


def _setup_happy_path(monkeypatch, *, fetch_content_from_github, commit_result=True, pr_url="https://github.com/example/project/pull/42"):
    source = "def add(left, right):\n    return left + right\n"
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {
            "src/example.py": [
                {"function_name": "add", "block_type": "function", "generated_docstring": "Add two values."}
            ]
        },
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_repo_tree",
        lambda repo_path, token, branch, provider: [{"type": "file", "path": "src/example.py"}],
    )
    monkeypatch.setattr("services.docstring_pr_services.clone_repository", _fake_clone)
    monkeypatch.setattr(
        "services.docstring_pr_services.read_file_content_from_local",
        lambda temp_dir, file_path: source,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services._run_ruff_on_patched_files", lambda patched_files: patched_files
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.list_open_github_pull_requests",
        lambda repo_path, base_branch, token: [],
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.ensure_github_branch",
        lambda repo_path, base_branch, suggestion_branch, token: True,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.fetch_content_from_github",
        fetch_content_from_github,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.commit_files_to_github_branch",
        lambda *args, **kwargs: commit_result,
    )
    monkeypatch.setattr(
        "services.docstring_pr_services.create_github_pull_request",
        lambda *args, **kwargs: pr_url,
    )


def test_create_python_docstring_pull_request_succeeds_for_new_file(monkeypatch):
    _setup_happy_path(monkeypatch, fetch_content_from_github=lambda repo_path, branch, file_path, token: None)

    result = create_python_docstring_pull_request(
        "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
    )

    assert result["status"] == "success"
    assert result["pull_request_url"] == "https://github.com/example/project/pull/42"
    assert result["files_changed"] == 1
    assert result["docstrings_added"] == 1
    assert result["changed_files"] == ["src/example.py"]


def test_create_python_docstring_pull_request_succeeds_when_fetch_raises(monkeypatch):
    def raising_fetch(repo_path, branch, file_path, token):
        raise GitHubApiError("not found")

    _setup_happy_path(monkeypatch, fetch_content_from_github=raising_fetch)

    result = create_python_docstring_pull_request(
        "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
    )

    assert result["status"] == "success"
    assert result["changed_files"] == ["src/example.py"]


def test_create_python_docstring_pull_request_raises_when_commit_fails(monkeypatch):
    _setup_happy_path(
        monkeypatch,
        fetch_content_from_github=lambda repo_path, branch, file_path, token: None,
        commit_result=False,
    )

    with pytest.raises(DocstringPullRequestError, match="Could not commit docstring suggestions"):
        create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )


def test_create_python_docstring_pull_request_wraps_github_api_error(monkeypatch):
    def raising_create_pr(*args, **kwargs):
        raise GitHubApiError("permission denied")

    _setup_happy_path(monkeypatch, fetch_content_from_github=lambda repo_path, branch, file_path, token: None)
    monkeypatch.setattr("services.docstring_pr_services.create_github_pull_request", raising_create_pr)

    with pytest.raises(DocstringPullRequestError, match="permission denied"):
        create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )


def test_create_python_docstring_pull_request_raises_when_pr_url_missing(monkeypatch):
    _setup_happy_path(
        monkeypatch,
        fetch_content_from_github=lambda repo_path, branch, file_path, token: None,
        pr_url=None,
    )

    with pytest.raises(DocstringPullRequestError, match="Could not create the GitHub pull request"):
        create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )


def test_create_python_docstring_pull_request_reraises_repository_access_error(monkeypatch):
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {"src/example.py": [{}]},
    )

    @contextmanager
    def raising_clone(repo_url, token, base_branch, provider):
        raise RepositoryAccessError("repo not accessible", status_code=404)
        yield  # pragma: no cover - unreachable, keeps this a generator function

    monkeypatch.setattr("services.docstring_pr_services.clone_repository", raising_clone)

    with pytest.raises(DocstringPullRequestError, match="repo not accessible"):
        create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )


def test_create_python_docstring_pull_request_reraises_unexpected_errors(monkeypatch):
    monkeypatch.setattr(
        "services.docstring_pr_services._load_generated_suggestions",
        lambda repo_path, branch: {"src/example.py": [{}]},
    )

    @contextmanager
    def raising_clone(repo_url, token, base_branch, provider):
        raise ValueError("boom")
        yield  # pragma: no cover - unreachable, keeps this a generator function

    monkeypatch.setattr("services.docstring_pr_services.clone_repository", raising_clone)

    with pytest.raises(ValueError, match="boom"):
        create_python_docstring_pull_request(
            "github", "example/project", "secret", "main", "autodocs/suggestions", "Add suggested docstrings"
        )
