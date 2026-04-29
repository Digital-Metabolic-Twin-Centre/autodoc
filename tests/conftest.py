import pytest


@pytest.fixture(autouse=True)
def isolate_log_dirs(monkeypatch, tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(log_dir))
