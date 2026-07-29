import re

_URL_CREDENTIAL_PATTERN = re.compile(r"://[^\s/@]+:[^\s/@]+@")
_KNOWN_TOKEN_PATTERN = re.compile(
    r"\b(ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|ghu_[A-Za-z0-9]{20,}|ghs_[A-Za-z0-9]{20,}"
    r"|ghr_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9\-_]{15,})\b"
)


def redact_secrets(text: str | None) -> str | None:
    """
    Strip embedded clone-URL credentials and known token formats out of free text.

    Git clone URLs carry access tokens as basic-auth credentials
    (``https://x-access-token:{token}@...``), and git can echo that URL back
    verbatim in its own error output. This scrubs both that pattern and
    recognizable GitHub/GitLab token prefixes from any text before it is
    logged, raised, or persisted.

    Args:
        text (str | None): Text that may contain credentials.
    Returns:
        str | None: The same text with credentials replaced by placeholders.

    """
    if not text:
        return text
    redacted = _URL_CREDENTIAL_PATTERN.sub("://***:***@", text)
    redacted = _KNOWN_TOKEN_PATTERN.sub("***REDACTED-TOKEN***", redacted)
    return redacted
