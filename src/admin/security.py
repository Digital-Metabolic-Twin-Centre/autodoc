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
    Checks for required admin authentication configuration.

        Returns:
            str | None: An error message if configuration is missing, otherwise None.

    """
    if not ADMIN_PASSWORD:
        return "ADMIN_PASSWORD must be configured to sign in to the admin dashboard."
    if not ADMIN_SECRET_KEY:
        return "ADMIN_SECRET_KEY must be configured to sign in to the admin dashboard."
    return None


def _require_secret() -> str:
    """
    Checks for the presence of the ADMIN_SECRET_KEY and raises an exception if not configured.

    Returns:
        str: The ADMIN_SECRET_KEY if configured.

    """
    if not ADMIN_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_SECRET_KEY must be configured to use the admin dashboard.",
        )
    return ADMIN_SECRET_KEY


def _build_fernet() -> Fernet:
    """
    Constructs a Fernet encryption object using a hashed secret.

        Returns:
            Fernet: A Fernet object for encryption and decryption.

    """
    secret = _require_secret().encode("utf-8")
    digest = hashlib.sha256(secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(token: str) -> str:
    """
    Encrypts a given token using a Fernet symmetric encryption scheme.

        Args:
            token (str): The plaintext token to be encrypted.

        Returns:
            str: The encrypted token as a base64-encoded string.

    """
    return _build_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token: str) -> str:
    """
    Decrypts a given token using a Fernet key.

    Args:
        token (str): The encrypted token to be decrypted.

    Returns:
        str: The decrypted token as a string.

    """
    return _build_fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def validate_admin_credentials(username: str, password: str) -> str:
    """
    Validate admin credentials against stored values.

        Args:
            username (str): The admin username to validate.
            password (str): The admin password to validate.

        Returns:
            str: The validated admin username if credentials are correct.

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
    Generate a HMAC SHA256 signature for the given value.

    Args:
        value (str): The input string to be signed.

    Returns:
        str: The hexadecimal representation of the HMAC signature.

    """
    secret = _require_secret().encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def create_admin_session(username: str) -> str:
    """
    Create an admin session token for the given username.

        Args:
            username (str): The username for which to create the session.

        Returns:
            str: A base64 encoded session token containing the username and signature.

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
    Validate and decode an admin session token.

        Args:
            session_value (str | None): The session token to validate.

        Returns:
            str | None: The admin username if valid, otherwise None.

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
    Sets an admin session cookie in the provided response.

        Args:
            response (Response): The response object to set the cookie on.
            username (str): The username for the admin session.

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
    Clears the admin session by deleting the session cookie.

        Args:
            response (Response): The response object from which the cookie will be deleted.

        Returns:
            None: This function does not return a value.

    """
    response.delete_cookie(ADMIN_SESSION_COOKIE)


def require_admin(request: Request) -> str:
    """
    Checks if the user is an admin based on the session cookie.

    Args:
        request (Request): The HTTP request object containing cookies.

    Returns:
        str: The username of the admin if authenticated, otherwise raises an HTTPException.

    """
    username = read_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE))
    if username:
        return username
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail="Admin authentication required.",
        headers={"Location": "/admin/login"},
    )


def ensure_csrf_token(request: Request, response: Response) -> str:
    """
    Ensure a CSRF token is created and set in the response cookie.

    Args:
        request (Request): The incoming request object.
        response (Response): The response object to set the cookie on.

    Returns:
        str: The generated CSRF token.

    """
    csrf_token = get_or_create_csrf_token(request)
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
    Retrieve or create a CSRF token from the request cookies.

        Args:
            request (Request): The HTTP request object containing cookies.

        Returns:
            str: The CSRF token as a string.

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
