import base64
import hashlib
import hmac
import json
import secrets
from time import time

from cryptography.fernet import Fernet
from fastapi import Form, HTTPException, Request, Response, status

from admin.settings import (
    ADMIN_CSRF_COOKIE,
    ADMIN_PASSWORD,
    ADMIN_SECRET_KEY,
    ADMIN_SESSION_COOKIE,
    ADMIN_SESSION_MAX_AGE,
    ADMIN_USERNAME,
)


def admin_auth_config_error() -> str | None:
    """
    Validate required admin authentication configuration.

    Args:
        None.
    Returns:
        str | None: Error message if configuration is missing, otherwise None.

    """
    if not ADMIN_PASSWORD:
        return "ADMIN_PASSWORD must be configured to sign in to the admin dashboard."
    if not ADMIN_SECRET_KEY:
        return "ADMIN_SECRET_KEY must be configured to sign in to the admin dashboard."
    return None


def _require_secret() -> str:
    """
    Return the configured admin secret key.

    Args: None.
    Returns: str: The configured admin secret key.
    """
    if not ADMIN_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_SECRET_KEY must be configured to use the admin dashboard.",
        )
    return ADMIN_SECRET_KEY


def _build_fernet() -> Fernet:
    """
    Create a Fernet instance from the configured secret.
    Args:
        None.
    Returns:
        Fernet: Fernet encryption instance derived from the secret hash.

    """
    secret = _require_secret().encode("utf-8")
    digest = hashlib.sha256(secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(token: str) -> str:
    """
    Encrypt a token using the configured Fernet key.

    Args:
        token (str): Plaintext token to encrypt.
    Returns:
        str: Encrypted token encoded as a UTF-8 string.

    """
    return _build_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token: str) -> str:
    """
    Decrypt an encrypted token string.

    Args:
        token (str): Encrypted token to decrypt.

    Returns:
        str: Decrypted token value.

    """
    return _build_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def validate_admin_credentials(username: str, password: str) -> str:
    """
    Validate administrator credentials against configured values.

    Args: username (str): Admin username; password (str): Admin password.
    Returns: str: The validated admin username.
    """
    config_error = admin_auth_config_error()
    if config_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=config_error,
        )
    valid_username = secrets.compare_digest(username, ADMIN_USERNAME)
    valid_password = secrets.compare_digest(password, ADMIN_PASSWORD)
    if not (valid_username and valid_password):
        raise ValueError("Invalid admin credentials.")
    return username


def _sign_value(value: str) -> str:
    """
    Generate an HMAC-SHA256 hex signature for a string value.

    Args:
        value (str): Value to sign.
    Returns:
        str: Hexadecimal HMAC digest.

    """
    secret = _require_secret().encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def create_admin_session(username: str) -> str:
    """
    Create a signed admin session token for a username.

    Args:
        username (str): Username to include in the session payload.
    Returns:
        str: URL-safe signed session token.

    """
    payload = {
        "username": username,
        "issued_at": int(time()),
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8")
    signature = _sign_value(payload_b64)
    return f"{payload_b64}.{signature}"


def read_admin_session(session_value: str | None) -> str | None:
    """
    Validate and read a signed admin session token.

    Args:
        session_value (str | None): Encoded session payload and signature.
    Returns:
        str | None: Admin username if valid and unexpired, otherwise None.

    """
    if not ADMIN_SECRET_KEY:
        return None
    if not session_value or "." not in session_value:
        return None
    payload_b64, signature = session_value.rsplit(".", 1)
    expected_signature = _sign_value(payload_b64)
    if not hmac.compare_digest(signature, expected_signature):
        return None
    try:
        payload_json = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode(
            "utf-8"
        )
        payload = json.loads(payload_json)
    except Exception:
        return None
    username = payload.get("username")
    issued_at = payload.get("issued_at", 0)
    if not isinstance(username, str) or username != ADMIN_USERNAME:
        return None
    if int(time()) - int(issued_at) > ADMIN_SESSION_MAX_AGE:
        return None
    return username


def set_admin_session(response: Response, username: str) -> None:
    """
    Set the admin session cookie on the response.

    Args:
        response (Response): HTTP response to update; username (str): Admin username for the
        session.
    Returns:
        None: This function does not return a value.

    """
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        create_admin_session(username),
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=ADMIN_SESSION_MAX_AGE,
    )


def clear_admin_session(response: Response) -> None:
    """
    Clear the admin session cookie from the response.

    Args:
        response (Response): HTTP response whose admin session cookie is deleted.
    Returns:
        None: This function does not return a value.

    """
    response.delete_cookie(ADMIN_SESSION_COOKIE)


def require_admin(request: Request) -> str:
    """
    Validate the admin session and return the authenticated username.

    Args:
        request (Request): Incoming request containing admin session cookies.
    Returns:
        str: Authenticated admin username.

    """
    username = read_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE))
    if username:
        return username
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail="Admin authentication required.",
        headers={"Location": "/admin/login"},
    )


def ensure_csrf_token(
    request: Request, response: Response, csrf_token: str | None = None
) -> str:
    """
    Ensure a CSRF token exists and set it as a response cookie.

    Args:
        request (Request): Incoming request used to retrieve or create the token.
        response (Response): Response on which to set the CSRF cookie.
        csrf_token (str | None): Optional token to use instead of generating one.

    Returns:
        str: The CSRF token set on the response.

    """
    csrf_token = csrf_token or get_or_create_csrf_token(request)
    response.set_cookie(
        ADMIN_CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=False,
        samesite="lax",
    )
    return csrf_token


def get_or_create_csrf_token(request: Request) -> str:
    """
    Get an existing CSRF token from cookies or generate a new one.
    Args:
        request (Request): Incoming request containing cookie data.
    Returns:
        str: Existing admin CSRF token or a newly generated token.

    """
    return request.cookies.get(ADMIN_CSRF_COOKIE) or secrets.token_urlsafe(24)


async def verify_csrf(
    request: Request,
    csrf_token: str = Form(default=""),
) -> None:
    cookie_token = request.cookies.get(ADMIN_CSRF_COOKIE)
    header_token = request.headers.get("X-CSRF-Token")
    submitted_token = header_token or csrf_token
    if not cookie_token or not submitted_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing CSRF token.",
        )
    if not hmac.compare_digest(cookie_token, submitted_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token.",
        )
