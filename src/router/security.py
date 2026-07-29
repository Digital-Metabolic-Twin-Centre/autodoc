import os
import secrets
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

AUTODOC_API_KEY = os.getenv("AUTODOC_API_KEY", "")
API_KEY_HEADER = "X-API-Key"

RATE_LIMIT_MAX_REQUESTS = int(os.getenv("AUTODOC_RATE_LIMIT_MAX_REQUESTS", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("AUTODOC_RATE_LIMIT_WINDOW_SECONDS", "3600"))

_request_log: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()


def api_auth_config_error() -> str | None:
    """
    Validate that the public API key is configured.

    Args:
        None.
    Returns:
        str | None: Error message if AUTODOC_API_KEY is not configured, otherwise None.

    """
    if not AUTODOC_API_KEY:
        return "AUTODOC_API_KEY must be configured to use the public API."
    return None


def require_api_key(request: Request) -> str:
    """
    Validate the caller-supplied API key against the configured secret.

    Args:
        request (Request): Incoming request expected to carry an X-API-Key header.
    Returns:
        str: The validated API key.

    """
    config_error = api_auth_config_error()
    if config_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=config_error,
        )
    supplied_key = request.headers.get(API_KEY_HEADER, "")
    if not supplied_key or not secrets.compare_digest(supplied_key, AUTODOC_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
        )
    return supplied_key


def _client_identifier(request: Request) -> str:
    supplied_key = request.headers.get(API_KEY_HEADER)
    if supplied_key:
        return f"key:{supplied_key}"
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


def enforce_rate_limit(request: Request) -> None:
    """
    Reject the request if the caller has exceeded the allowed request rate.

    Requests are tracked per API key (falling back to client IP) in a fixed
    time window held in memory, so this only protects a single process.

    Args:
        request (Request): Incoming request used to identify the caller.
    Returns:
        None: This function does not return a value.

    """
    identifier = _client_identifier(request)
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    with _rate_limit_lock:
        timestamps = _request_log[identifier]
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()
        if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
            retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - timestamps[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        timestamps.append(now)
