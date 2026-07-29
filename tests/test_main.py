import importlib

import admin.database
import admin.jobs


def test_main_logs_warning_when_interrupted_runs_are_recovered(monkeypatch, caplog):
    import main as main_module

    monkeypatch.setattr(admin.database, "init_db", lambda: None)
    monkeypatch.setattr(admin.jobs, "reconcile_interrupted_runs", lambda: 3)

    with caplog.at_level("WARNING"):
        importlib.reload(main_module)

    assert any("Recovered 3 interrupted admin run(s)" in record.message for record in caplog.records)
