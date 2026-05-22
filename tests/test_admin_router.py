from types import SimpleNamespace

from admin.router import _read_artifact_preview, _run_log_entries


def test_run_log_entries_prioritize_key_logs(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "app.log").write_text("app\n", encoding="utf-8")
    (artifact_dir / "sphinx_build.log").write_text("sphinx\n", encoding="utf-8")
    (artifact_dir / "skipped_autoapi_files.txt").write_text("skip\n", encoding="utf-8")
    (artifact_dir / "notes.json").write_text("{}", encoding="utf-8")

    run = SimpleNamespace(
        artifact_dir=str(artifact_dir),
        log_path=str(artifact_dir / "app.log"),
    )

    entries = _run_log_entries(run)

    assert [entry["name"] for entry in entries] == [
        "app.log",
        "sphinx_build.log",
        "skipped_autoapi_files.txt",
    ]


def test_read_artifact_preview_truncates_large_files(tmp_path):
    artifact_path = tmp_path / "sphinx_build.log"
    artifact_path.write_text("x" * 20, encoding="utf-8")

    content, truncated = _read_artifact_preview(artifact_path, max_chars=10)

    assert content == "x" * 10
    assert truncated is True
