from pathlib import Path

import pytest

from utils.output_paths import (
    bind_repo_run_log_dir,
    build_repo_output_dir,
    build_repo_output_file,
    clear_repo_output_history,
    find_latest_repo_run_dir,
    validate_architecture_output_path,
)


def test_build_repo_output_dir_creates_provider_and_repo_scoped_folder():
    output_dir = build_repo_output_dir("octo-org/example-repo", "GitHub")

    assert "logs/github/octo-org__example-repo/app_" in output_dir
    assert output_dir.split("/logs/")[1].count("app_") == 1


def test_build_repo_output_file_reuses_repo_scoped_folder():
    output_file = build_repo_output_file("group/subgroup/project", "gitlab", "block_analysis.csv")

    assert output_file.endswith("block_analysis.csv")
    assert "logs/gitlab/group__subgroup__project/app_" in output_file


def test_find_latest_repo_run_dir_returns_latest(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    repo_dir = tmp_path / "github" / "octo-org__example-repo"
    (repo_dir / "app_20260428_100000").mkdir(parents=True)
    (repo_dir / "app_20260428_110000").mkdir(parents=True)

    latest = find_latest_repo_run_dir("octo-org/example-repo", "github")

    assert latest == str(repo_dir / "app_20260428_110000")


def test_clear_repo_output_history_removes_repo_folder(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    repo_dir = tmp_path / "github" / "octo-org__example-repo"
    (repo_dir / "app_20260428_100000").mkdir(parents=True)

    clear_repo_output_history("octo-org/example-repo", "github")

    assert not repo_dir.exists()


def test_bind_repo_run_log_dir_copies_previous_text_json_and_csv_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    repo_dir = tmp_path / "github" / "octo-org__example-repo"
    previous_run = repo_dir / "app_20260428_100000"
    previous_run.mkdir(parents=True)
    (previous_run / "block_analysis.csv").write_text("file_name\nexample.py\n", encoding="utf-8")
    (previous_run / "suggested_docstrings.json").write_text("{}", encoding="utf-8")
    (previous_run / "suggested_docstring.txt").write_text("docstring", encoding="utf-8")
    (previous_run / "app.log").write_text("log data", encoding="utf-8")

    bound_log_file = bind_repo_run_log_dir("octo-org/example-repo", "github")
    bound_dir = Path(bound_log_file).parent

    assert str(bound_dir).startswith(str(repo_dir / "app_"))
    assert (bound_dir / "block_analysis.csv").read_text(encoding="utf-8") == "file_name\nexample.py\n"
    assert (bound_dir / "suggested_docstrings.json").read_text(encoding="utf-8") == "{}"
    assert (bound_dir / "suggested_docstring.txt").read_text(encoding="utf-8") == "docstring"
    assert not (bound_dir / "non_preserved.log").exists()


def test_validate_architecture_output_path_accepts_docs_tree_path():
    assert validate_architecture_output_path("docs/project/architecture.rst") == "docs/project/architecture.rst"
    assert validate_architecture_output_path("/docs/project/architecture.rst/") == "docs/project/architecture.rst"


@pytest.mark.parametrize(
    "output_path",
    [
        "",
        "../outside.rst",
        "docs/../../outside.rst",
        "notes/architecture.rst",
    ],
)
def test_validate_architecture_output_path_rejects_paths_outside_docs_tree(output_path):
    with pytest.raises(ValueError):
        validate_architecture_output_path(output_path)
