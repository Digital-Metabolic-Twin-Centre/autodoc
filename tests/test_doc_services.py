import json
from contextlib import contextmanager

import pytest

import services.doc_services as doc_services_module
from services.architecture_services import ArchitectureAnalysisError
from services.doc_services import (
    RepoAnalysisError,
    _file_matches_target_folders,
    _load_reusable_suggestions,
    _normalize_target_folders,
    analyse_repo,
)
from services.workflow_service import execute_architecture_generation_request


def test_normalize_target_folders_trims_whitespace_and_slashes():
    assert _normalize_target_folders([" src ", "/docs/", "nested/path//"]) == [
        "src",
        "docs",
        "nested/path",
    ]


def test_normalize_target_folders_discards_empty_values():
    assert _normalize_target_folders(["", "  ", "/"]) == []


def test_normalize_target_folders_strips_stray_quotes():
    assert _normalize_target_folders(['"api"', "'tools'", '"webKinPred"']) == [
        "api",
        "tools",
        "webKinPred",
    ]


def test_file_matches_target_folders_returns_true_when_no_targets():
    assert _file_matches_target_folders("src/main.py", []) is True


def test_file_matches_target_folders_matches_nested_paths():
    targets = ["src", "docs/guides"]

    assert _file_matches_target_folders("src/main.py", targets) is True
    assert _file_matches_target_folders("docs/guides/setup.md", targets) is True
    assert _file_matches_target_folders("docs/api/index.md", targets) is False
    assert _file_matches_target_folders("scripts/build.py", targets) is False


def test_load_reusable_suggestions_returns_empty_cache_shape_when_no_runs(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))

    suggestions = _load_reusable_suggestions("octo-org/example-repo", "github", "main")

    assert suggestions == {"exact": {}, "fuzzy": {}}


def test_load_reusable_suggestions_reads_matching_run_even_if_latest_branch_differs(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    repo_dir = tmp_path / "github" / "octo-org__example-repo"
    old_run = repo_dir / "app_20260428_100000"
    new_run = repo_dir / "app_20260428_110000"
    old_run.mkdir(parents=True)
    new_run.mkdir(parents=True)
    (old_run / "suggested_docstrings.json").write_text(
        json.dumps(
            {
                "repo_path": "octo-org/example-repo",
                "branch": "main",
                "suggestions": [
                    {
                        "file_path": "src/job_views.py",
                        "function_name": "build_job",
                        "block_type": "function",
                        "line_number": 12,
                        "language": "python",
                        "generated_docstring": "Build a job.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (new_run / "suggested_docstrings.json").write_text(
        json.dumps({"repo_path": "octo-org/example-repo", "branch": "dev", "suggestions": []}),
        encoding="utf-8",
    )

    suggestions = _load_reusable_suggestions("octo-org/example-repo", "github", "main")

    assert suggestions["exact"][("src/job_views.py", "build_job", "function", 12, "python")] == "Build a job."
    assert suggestions["fuzzy"][("src/job_views.py", "build_job", "function", "python")] == "Build a job."


def test_load_reusable_suggestions_merges_partial_runs_for_same_branch(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    repo_dir = tmp_path / "github" / "octo-org__example-repo"
    older_run = repo_dir / "app_20260428_100000"
    newer_run = repo_dir / "app_20260428_110000"
    older_run.mkdir(parents=True)
    newer_run.mkdir(parents=True)
    (older_run / "suggested_docstrings.json").write_text(
        json.dumps(
            {
                "repo_path": "octo-org/example-repo",
                "branch": "main",
                "suggestions": [
                    {
                        "file_path": "src/job_views.py",
                        "function_name": "build_job",
                        "block_type": "function",
                        "line_number": 12,
                        "language": "python",
                        "generated_docstring": "Build a job.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (newer_run / "suggested_docstrings.json").write_text(
        json.dumps(
            {
                "repo_path": "octo-org/example-repo",
                "branch": "main",
                "suggestions": [
                    {
                        "file_path": "src/publish.py",
                        "function_name": "publish_docs",
                        "block_type": "function",
                        "line_number": 22,
                        "language": "python",
                        "generated_docstring": "Publish the docs.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    suggestions = _load_reusable_suggestions("octo-org/example-repo", "github", "main")

    assert suggestions["exact"][("src/job_views.py", "build_job", "function", 12, "python")] == "Build a job."
    assert suggestions["exact"][("src/publish.py", "publish_docs", "function", 22, "python")] == "Publish the docs."
    assert suggestions["fuzzy"][("src/job_views.py", "build_job", "function", "python")] == "Build a job."
    assert suggestions["fuzzy"][("src/publish.py", "publish_docs", "function", "python")] == "Publish the docs."


def test_analyse_repo_only_loads_cache_when_reuse_doc_true(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    monkeypatch.setattr(doc_services_module, "extract_repo_path", lambda repo_url, provider: repo_url)

    @contextmanager
    def fake_clone_repository(repo_url, token, branch, provider):
        yield str(tmp_path)

    monkeypatch.setattr(doc_services_module, "clone_repository", fake_clone_repository)
    monkeypatch.setattr(doc_services_module, "fetch_repo_tree", lambda *args, **kwargs: [])

    load_calls = []
    original_loader = doc_services_module._load_reusable_suggestions

    def spy_loader(repo_path, provider, branch):
        load_calls.append((repo_path, provider, branch))
        return original_loader(repo_path, provider, branch)

    monkeypatch.setattr(doc_services_module, "_load_reusable_suggestions", spy_loader)

    with pytest.raises(RepoAnalysisError):
        analyse_repo("github", "octo-org/no-reuse-repo", "token", "main", reuse_doc=False)
    assert load_calls == []

    with pytest.raises(RepoAnalysisError):
        analyse_repo("github", "octo-org/reuse-repo", "token", "main", reuse_doc=True)
    assert load_calls == [("octo-org/reuse-repo", "github", "main")]


def test_execute_architecture_generation_request_never_commits(monkeypatch):
    from models.repo_request import ArchitectureGenerationRequest

    monkeypatch.setattr(
        "services.workflow_service.generate_architecture_draft",
        lambda **kwargs: {
            "status": "success",
            "draft_id": "arch_123",
            "draft_path": "/tmp/architecture_draft_arch_123.rst",
            "proposed_output_path": "docs/project/architecture.rst",
            "sections_summary": [],
            "gaps": [],
            "diagram_paths": [],
            "artifact_dir": "/tmp",
        },
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("generation must never call a provider write helper")

    monkeypatch.setattr("utils.git_utils.create_a_file", _fail_if_called)

    req = ArchitectureGenerationRequest(
        provider="github",
        repo_url="example/project",
        token="secret",
        branch="main",
    )

    result = execute_architecture_generation_request(req)

    assert result.response["status"] == "success"
    assert result.response["approval_required"] is True
    assert result.draft_id == "arch_123"


def test_execute_architecture_generation_request_surfaces_repository_access_failure(monkeypatch):
    from models.repo_request import ArchitectureGenerationRequest

    def fail_generation(**kwargs):
        raise ArchitectureAnalysisError(
            "GitHub rejected access to repository 'example/private' on branch 'main'.",
            status_code=403,
        )

    monkeypatch.setattr("services.workflow_service.generate_architecture_draft", fail_generation)

    req = ArchitectureGenerationRequest(
        provider="github",
        repo_url="example/private",
        token="secret",
        branch="main",
    )

    with pytest.raises(ArchitectureAnalysisError) as exc_info:
        execute_architecture_generation_request(req)

    assert exc_info.value.status_code == 403
