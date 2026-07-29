from admin.settings import _env_flag


def test_env_flag_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("AUTODOC_TEST_FLAG", raising=False)

    assert _env_flag("AUTODOC_TEST_FLAG", True) is True
    assert _env_flag("AUTODOC_TEST_FLAG", False) is False


def test_env_flag_parses_explicit_falsy_value(monkeypatch):
    monkeypatch.setenv("AUTODOC_TEST_FLAG", "false")

    assert _env_flag("AUTODOC_TEST_FLAG", True) is False


def test_env_flag_parses_explicit_truthy_value(monkeypatch):
    monkeypatch.setenv("AUTODOC_TEST_FLAG", "yes")

    assert _env_flag("AUTODOC_TEST_FLAG", False) is True
