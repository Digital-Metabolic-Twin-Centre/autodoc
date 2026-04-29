from pathlib import Path

from utils.output_paths import (
    build_repo_output_dir,
    build_repo_output_file,
    clear_repo_output_history,
    find_latest_repo_run_dir,
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
