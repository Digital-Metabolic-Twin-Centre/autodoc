import importlib
from asyncio import run

import httpx
import pytest

import admin.database
import admin.jobs


def test_main_logs_warning_when_interrupted_runs_are_recovered(monkeypatch, caplog):
    import main as main_module

    monkeypatch.setattr(admin.database, "init_db", lambda: None)
    monkeypatch.setattr(admin.jobs, "reconcile_interrupted_runs", lambda: 3)

    with caplog.at_level("WARNING"):
        importlib.reload(main_module)

    assert any("Recovered 3 interrupted admin run(s)" in record.message for record in caplog.records)


def _reload_with_env(monkeypatch, **env):
    """
    Reload main.py with the given env vars set, then restore real env/state
    afterward so later tests (some of which import `main` themselves) don't
    inherit a mutated TrustedHost/CORS configuration from this test.
    """
    import main as main_module

    monkeypatch.setattr(admin.database, "init_db", lambda: None)
    monkeypatch.setattr(admin.jobs, "reconcile_interrupted_runs", lambda: 0)
    monkeypatch.delenv("AUTODOC_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("AUTODOC_CORS_ORIGINS", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    importlib.reload(main_module)
    return main_module


@pytest.fixture
def reloaded_main(monkeypatch):
    try:
        yield lambda **env: _reload_with_env(monkeypatch, **env)
    finally:
        monkeypatch.undo()
        import main as main_module

        importlib.reload(main_module)


def test_main_defaults_to_permissive_trusted_hosts_and_no_cors_origins(reloaded_main):
    main_module = reloaded_main()

    assert main_module.ALLOWED_HOSTS == ["*"]
    assert main_module.CORS_ALLOWED_ORIGINS == []


def test_main_parses_comma_separated_env_lists(reloaded_main):
    main_module = reloaded_main(
        AUTODOC_ALLOWED_HOSTS=" docs.example.com , api.example.com ,,",
        AUTODOC_CORS_ORIGINS="https://app.example.com",
    )

    assert main_module.ALLOWED_HOSTS == ["docs.example.com", "api.example.com"]
    assert main_module.CORS_ALLOWED_ORIGINS == ["https://app.example.com"]


def test_main_trusted_host_middleware_rejects_unrecognized_host(reloaded_main):
    main_module = reloaded_main(AUTODOC_ALLOWED_HOSTS="docs.example.com")

    async def _request():
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://untrusted-host") as client:
            return await client.get("/")

    response = run(_request())

    assert response.status_code == 400


def test_main_trusted_host_middleware_accepts_configured_host(reloaded_main):
    main_module = reloaded_main(AUTODOC_ALLOWED_HOSTS="docs.example.com")

    async def _request():
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://docs.example.com") as client:
            return await client.get("/")

    response = run(_request())

    assert response.status_code != 400


def test_main_cors_middleware_allows_configured_origin_only(reloaded_main):
    main_module = reloaded_main(AUTODOC_CORS_ORIGINS="https://app.example.com")

    async def _request(origin):
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/", headers={"Origin": origin})

    allowed_response = run(_request("https://app.example.com"))
    denied_response = run(_request("https://attacker.example"))

    assert allowed_response.headers.get("access-control-allow-origin") == "https://app.example.com"
    assert "access-control-allow-origin" not in denied_response.headers


def test_main_cors_middleware_allows_no_origins_by_default(reloaded_main):
    main_module = reloaded_main()

    async def _request():
        transport = httpx.ASGITransport(app=main_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/", headers={"Origin": "https://anywhere.example"})

    response = run(_request())

    assert "access-control-allow-origin" not in response.headers
