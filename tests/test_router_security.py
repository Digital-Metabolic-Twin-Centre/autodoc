import time

from starlette.requests import Request

import router.security as security
from router.security import _client_identifier, enforce_rate_limit


def _make_request(headers=None, client=("127.0.0.1", 12345)):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/generate",
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in (headers or {}).items()
        ],
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


def test_client_identifier_falls_back_to_ip_when_no_api_key_header():
    request = _make_request(headers={}, client=("203.0.113.5", 4321))

    assert _client_identifier(request) == "ip:203.0.113.5"


def test_client_identifier_returns_unknown_when_no_client_info():
    request = _make_request(headers={}, client=None)

    assert _client_identifier(request) == "ip:unknown"


def test_enforce_rate_limit_purges_expired_timestamps(monkeypatch):
    monkeypatch.setattr(security, "RATE_LIMIT_MAX_REQUESTS", 5)
    monkeypatch.setattr(security, "RATE_LIMIT_WINDOW_SECONDS", 60)
    request = _make_request(headers={"X-API-Key": "some-key"})
    identifier = "key:some-key"
    security._request_log[identifier].clear()
    security._request_log[identifier].append(time.monotonic() - 3600)

    enforce_rate_limit(request)

    assert len(security._request_log[identifier]) == 1
