import json

from services.doc_services import (
    _file_matches_target_folders,
    _load_reusable_suggestions,
    _normalize_target_folders,
)


def test_normalize_target_folders_trims_whitespace_and_slashes():
    assert _normalize_target_folders([" src ", "/docs/", "nested/path//"]) == [
        "src",
        "docs",
        "nested/path",
    ]


def test_normalize_target_folders_discards_empty_values():
    assert _normalize_target_folders(["", "  ", "/"]) == []


def test_file_matches_target_folders_returns_true_when_no_targets():
    assert _file_matches_target_folders("src/main.py", []) is True


def test_file_matches_target_folders_matches_nested_paths():
    targets = ["src", "docs/guides"]

    assert _file_matches_target_folders("src/main.py", targets) is True
    assert _file_matches_target_folders("docs/guides/setup.md", targets) is True
    assert _file_matches_target_folders("docs/api/index.md", targets) is False
    assert _file_matches_target_folders("scripts/build.py", targets) is False


def test_load_reusable_suggestions_reads_latest_matching_run(monkeypatch, tmp_path):
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

    assert suggestions["exact"][
        ("src/job_views.py", "build_job", "function", 12, "python")
    ] == "Build a job."
    assert suggestions["fuzzy"][
        ("src/job_views.py", "build_job", "function", "python")
    ] == "Build a job."
