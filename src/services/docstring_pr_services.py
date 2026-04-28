import ast
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Union

from config.log_config import get_logger
from utils.git_utils import (
    GitHubApiError,
    commit_files_to_github_branch,
    create_github_pull_request,
    ensure_github_branch,
    extract_repo_path,
    fetch_content_from_github,
    fetch_repo_tree,
)
from utils.output_paths import build_repo_output_file

logger = get_logger(__name__)

DocstringNode = Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]


@dataclass
class DocstringInsertion:
    name: str
    kind: str
    line_number: int
    insert_index: int
    indent: str
    code: str


@dataclass
class PatchedPythonFile:
    content: str
    inserted: List[DocstringInsertion]


class DocstringPullRequestError(RuntimeError):
    """Raised when creating a docstring suggestion pull request fails."""


def _format_python_docstring(docstring: str, indent: str) -> List[str]:
    cleaned = docstring.strip()
    if cleaned.startswith(('"""', "'''")) and cleaned.endswith(('"""', "'''")):
        cleaned = cleaned[3:-3].strip()

    content_width = max(40, 100 - len(indent))
    cleaned_lines = []
    for line in cleaned.splitlines():
        stripped = line.rstrip()
        if not stripped:
            cleaned_lines.append("")
            continue
        leading_spaces = stripped[: len(stripped) - len(stripped.lstrip())]
        cleaned_lines.extend(
            textwrap.wrap(stripped, width=content_width, subsequent_indent=leading_spaces)
            or [""]
        )

    if not cleaned_lines:
        cleaned_lines = ["TODO: Add documentation."]

    if len(cleaned_lines) == 1:
        return [f'{indent}"""{cleaned_lines[0]}"""']

    formatted = [f'{indent}"""']
    formatted.extend(f"{indent}{line}" if line else indent for line in cleaned_lines)
    if any(line.startswith((" ", "\t")) for line in cleaned_lines):
        formatted.append(indent)
    formatted.append(f'{indent}"""')
    return formatted


def _node_insert_index(node: DocstringNode) -> int:
    first_body_node = node.body[0]
    return first_body_node.lineno - 1


def _find_missing_python_docstrings(content: str) -> List[DocstringInsertion]:
    tree = ast.parse(content)
    insertions: List[DocstringInsertion] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not node.body or ast.get_docstring(node) is not None:
            continue

        code = ast.get_source_segment(content, node) or ""
        if isinstance(node, ast.ClassDef):
            kind = "class"
        elif isinstance(node, ast.AsyncFunctionDef):
            kind = "async_function"
        else:
            kind = "function"
        insertions.append(
            DocstringInsertion(
                name=node.name,
                kind=kind,
                line_number=node.lineno,
                insert_index=_node_insert_index(node),
                indent=" " * (node.col_offset + 4),
                code=code,
            )
        )

    return sorted(insertions, key=lambda insertion: insertion.insert_index, reverse=True)


def patch_python_docstrings(
    content: str,
    generator: Callable[[DocstringInsertion], Optional[str]],
    max_docstrings: int = 50,
) -> PatchedPythonFile:
    """
    Inserts generated docstrings into Python code using AST-derived insertion points.
    """
    insertions = _find_missing_python_docstrings(content)
    if not insertions:
        return PatchedPythonFile(content=content, inserted=[])

    lines = content.splitlines()
    inserted: List[DocstringInsertion] = []
    remaining = max_docstrings

    for insertion in insertions:
        if remaining <= 0:
            break
        docstring = generator(insertion)
        if not docstring:
            logger.warning(
                "Skipping %s %s because docstring generation failed.",
                insertion.kind,
                insertion.name,
            )
            continue
        formatted = _format_python_docstring(docstring, insertion.indent)
        lines[insertion.insert_index:insertion.insert_index] = formatted
        inserted.append(insertion)
        remaining -= 1

    if not inserted:
        return PatchedPythonFile(content=content, inserted=[])

    return PatchedPythonFile(content="\n".join(lines) + "\n", inserted=list(reversed(inserted)))


def _load_generated_suggestions(repo_path: str, branch: str) -> Dict[str, List[dict]]:
    suggestions_path = build_repo_output_file(repo_path, "github", "suggested_docstrings.json")
    if not os.path.exists(suggestions_path):
        raise DocstringPullRequestError(
            "No generated docstring suggestions found. Run /generate for this repo "
            "and branch first."
        )

    with open(suggestions_path, "r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)

    if payload.get("repo_path") != repo_path or payload.get("branch") != branch:
        raise DocstringPullRequestError(
            "Stored suggestions do not match this repo/branch. Run /generate for this "
            "repo and branch before creating a suggestion PR."
        )

    suggestions_by_file: Dict[str, List[dict]] = {}
    for suggestion in payload.get("suggestions", []):
        if suggestion.get("language") != "python":
            continue
        file_path = suggestion.get("file_path", "")
        if file_path:
            suggestions_by_file.setdefault(file_path, []).append(suggestion)
    return suggestions_by_file


def _suggestion_generator(suggestions: List[dict]) -> Callable[[DocstringInsertion], Optional[str]]:
    used_indexes = set()

    def generate(insertion: DocstringInsertion) -> Optional[str]:
        for index, suggestion in enumerate(suggestions):
            if index in used_indexes:
                continue
            if suggestion.get("function_name") != insertion.name:
                continue
            if suggestion.get("block_type") != insertion.kind:
                continue
            used_indexes.add(index)
            return suggestion.get("generated_docstring")
        return None

    return generate


def _build_pull_request_body(base_branch: str, files_changed: Dict[str, PatchedPythonFile]) -> str:
    docstring_count = sum(len(patched.inserted) for patched in files_changed.values())
    file_lines = "\n".join(
        f"- `{file_path}`: {len(patched.inserted)} docstring(s)"
        for file_path, patched in files_changed.items()
    )
    return (
        "## Summary\n\n"
        f"Adds {docstring_count} generated Python docstring suggestion(s) for review.\n\n"
        "## Changed files\n\n"
        f"{file_lines}\n\n"
        "These changes were generated by Auto-Doc and should be reviewed before merge.\n\n"
        f"Base branch: `{base_branch}`\n"
    )


def _run_ruff_on_patched_files(files: Dict[str, PatchedPythonFile]) -> Dict[str, PatchedPythonFile]:
    """
    Runs ruff formatting/fixes on patched Python files before they are committed.
    """
    if not files:
        return files

    with tempfile.TemporaryDirectory(prefix="autodoc-ruff-") as temp_dir:
        local_paths = []
        path_map = {}
        for file_path, patched in files.items():
            local_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(patched.content)
            local_paths.append(local_path)
            path_map[local_path] = file_path

        for command in (
            [sys.executable, "-m", "ruff", "format", *local_paths],
            [sys.executable, "-m", "ruff", "check", "--fix", *local_paths],
        ):
            result = subprocess.run(
                command,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning("Ruff cleanup failed: %s", result.stderr.strip() or result.stdout)
                return files

        cleaned_files = {}
        for local_path, file_path in path_map.items():
            with open(local_path, "r", encoding="utf-8") as file_handle:
                cleaned_files[file_path] = PatchedPythonFile(
                    content=file_handle.read(),
                    inserted=files[file_path].inserted,
                )
        return cleaned_files


def create_python_docstring_pull_request(
    provider: str,
    repo_url: str,
    token: str,
    base_branch: str,
    suggestion_branch: str,
    title: str,
    max_docstrings: int = 50,
) -> dict:
    """
    Creates a GitHub pull request with generated Python docstring suggestions.
    """
    if provider.lower() != "github":
        raise DocstringPullRequestError(
            "Python docstring pull requests currently support GitHub only."
        )

    repo_path = extract_repo_path(repo_url, "github")
    suggestions_by_file = _load_generated_suggestions(repo_path, base_branch)
    if not suggestions_by_file:
        raise DocstringPullRequestError(
            "No generated Python docstring suggestions were found. Run /generate first."
        )

    files = fetch_repo_tree(repo_path, token, branch=base_branch, provider="github")
    python_files = [
        item.get("path", "")
        for item in files
        if item.get("type") == "file" and item.get("path", "").endswith((".py", ".pyw"))
    ]
    if not python_files:
        raise DocstringPullRequestError("No Python files found on the selected branch.")

    remaining = max_docstrings
    patched_files: Dict[str, PatchedPythonFile] = {}
    for file_path in python_files:
        if remaining <= 0:
            break
        content = fetch_content_from_github(repo_path, base_branch, file_path, token)
        if not content:
            continue
        suggestions = suggestions_by_file.get(file_path)
        if not suggestions:
            continue
        try:
            patched = patch_python_docstrings(
                content,
                generator=_suggestion_generator(suggestions),
                max_docstrings=remaining,
            )
        except SyntaxError:
            logger.warning("Skipping %s because Python parsing failed.", file_path)
            continue
        if patched.inserted:
            patched_files[file_path] = patched
            remaining -= len(patched.inserted)

    if not patched_files:
        raise DocstringPullRequestError("No missing Python docstrings were patched.")

    patched_files = _run_ruff_on_patched_files(patched_files)

    branch_ready = ensure_github_branch(repo_path, base_branch, suggestion_branch, token)
    if not branch_ready:
        raise DocstringPullRequestError("Could not create or access the suggestion branch.")

    committed = commit_files_to_github_branch(
        repo_path,
        suggestion_branch,
        {file_path: patched.content for file_path, patched in patched_files.items()},
        token,
        "Add generated Python docstring suggestions",
    )
    if not committed:
        raise DocstringPullRequestError(
            "Could not commit docstring suggestions to the suggestion branch."
        )

    try:
        pr_url = create_github_pull_request(
            repo_path,
            suggestion_branch,
            base_branch,
            title,
            _build_pull_request_body(base_branch, patched_files),
            token,
        )
    except GitHubApiError as error:
        raise DocstringPullRequestError(str(error)) from error
    if not pr_url:
        raise DocstringPullRequestError("Could not create the GitHub pull request.")

    return {
        "status": "success",
        "provider": "github",
        "base_branch": base_branch,
        "suggestion_branch": suggestion_branch,
        "pull_request_url": pr_url,
        "files_changed": len(patched_files),
        "docstrings_added": sum(len(patched.inserted) for patched in patched_files.values()),
        "changed_files": sorted(patched_files.keys()),
    }
