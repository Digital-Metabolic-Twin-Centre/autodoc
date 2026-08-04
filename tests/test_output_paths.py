from pathlib import Path

import pytest

import utils.output_paths as output_paths
from utils.output_paths import (
    bind_repo_run_log_dir,
    build_repo_output_dir,
    build_repo_output_file,
    clear_repo_output_history,
    find_latest_repo_run_dir,
    validate_architecture_output_path,
)


def test_make_unique_run_dir_returns_distinct_dirs_for_back_to_back_calls(tmp_path):
    first = output_paths._make_unique_run_dir(str(tmp_path))
    second = output_paths._make_unique_run_dir(str(tmp_path))

    assert first != second
    assert Path(first).is_dir()
    assert Path(second).is_dir()


def test_make_unique_run_dir_retries_when_two_runs_land_on_the_same_timestamp(monkeypatch, tmp_path):
    """Simulates two concurrent runs whose clocks resolve to the identical microsecond."""
    fixed_timestamp = "20260804_120000_000000"

    class _FixedDateTime:
        @staticmethod
        def now():
            class _Instant:
                @staticmethod
                def strftime(_fmt):
                    return fixed_timestamp

            return _Instant()

    monkeypatch.setattr(output_paths, "datetime", _FixedDateTime)
    suffixes = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
    monkeypatch.setattr(output_paths.secrets, "token_hex", lambda _n: next(suffixes))

    base_dir = tmp_path / "github" / "octo-org__example-repo"
    # A prior "run" already claimed the directory the first attempt will try.
    (base_dir / f"app_{fixed_timestamp}_aaaaaa").mkdir(parents=True)

    result = output_paths._make_unique_run_dir(str(base_dir))

    assert result == str(base_dir / f"app_{fixed_timestamp}_bbbbbb")
    assert Path(result).is_dir()


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


def test_find_latest_repo_run_dir_returns_none_when_no_run_dirs_exist(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    repo_dir = tmp_path / "github" / "octo-org__example-repo"
    repo_dir.mkdir(parents=True)

    assert find_latest_repo_run_dir("octo-org/example-repo", "github") is None


def test_build_repo_output_dir_prunes_old_run_dirs_beyond_retention(monkeypatch, tmp_path):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    repo_dir = tmp_path / "github" / "octo-org__example-repo"
    for index in range(output_paths.LOG_RETENTION_COUNT + 2):
        (repo_dir / f"app_2026042{index}_100000").mkdir(parents=True)

    output_paths._cleanup_old_logs("octo-org/example-repo", "github")

    remaining = sorted(p.name for p in repo_dir.iterdir())
    assert len(remaining) == output_paths.LOG_RETENTION_COUNT


def test_cleanup_old_logs_logs_and_continues_when_rmtree_fails(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path))
    repo_dir = tmp_path / "github" / "octo-org__example-repo"
    for index in range(output_paths.LOG_RETENTION_COUNT + 1):
        (repo_dir / f"app_2026042{index}_100000").mkdir(parents=True)

    def failing_rmtree(path, ignore_errors=False):
        raise OSError("boom")

    monkeypatch.setattr(output_paths.shutil, "rmtree", failing_rmtree)

    with caplog.at_level("DEBUG"):
        output_paths._cleanup_old_logs("octo-org/example-repo", "github")

    assert any("Failed to clean up old log directory" in record.message for record in caplog.records)


def test_copy_previous_run_artifacts_skips_subdirectories(tmp_path):
    previous_run = tmp_path / "previous"
    previous_run.mkdir()
    (previous_run / "report.csv").write_text("data", encoding="utf-8")
    (previous_run / "nested_dir").mkdir()
    (previous_run / "nested_dir" / "inner.csv").write_text("nested", encoding="utf-8")
    output_dir = tmp_path / "output"

    output_paths._copy_previous_run_artifacts(str(previous_run), str(output_dir))

    assert (output_dir / "report.csv").exists()
    assert not (output_dir / "nested_dir").exists()


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
