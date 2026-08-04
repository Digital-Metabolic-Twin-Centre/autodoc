import re

_URL_CREDENTIAL_PATTERN = re.compile(r"://[^\s/@]+:[^\s/@]+@")
_KNOWN_TOKEN_PATTERN = re.compile(
    r"\b("
    r"ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|ghu_[A-Za-z0-9]{20,}|ghs_[A-Za-z0-9]{20,}"
    r"|ghr_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    # GitLab's gl<code>- token family: personal/project access (glpat-), deploy (gldt-),
    # runner auth (glrt-), CI job (glcbt-), pipeline trigger (glptt-), feed (glft-),
    # incoming mail (glimt-), agent (glagent-), SCIM (glsoat-), OAuth app secret (gloas-).
    r"|gl(?:pat|dt|rt|cbt|ptt|ft|imt|agent|soat|oas)-[A-Za-z0-9\-_]{15,}"
    r"|sk-[A-Za-z0-9_-]{16,}"  # OpenAI API keys (sk-..., sk-proj-..., sk-svcacct-...)
    r")\b"
)
# Matches an Authorization-style "Bearer <token>" / "Basic <token>" value in free text,
# independent of whether the token itself matches a known provider prefix above.
_AUTH_HEADER_VALUE_PATTERN = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)


def redact_secrets(text: str | None) -> str | None:
    """
    Strip embedded clone-URL credentials and known token formats out of free text.

    Git clone URLs carry access tokens as basic-auth credentials
    (``https://x-access-token:{token}@...``), and git can echo that URL back
    verbatim in its own error output. This scrubs that pattern, recognizable
    GitHub/GitLab/OpenAI token prefixes, and generic Bearer/Basic auth header
    values from any text before it is logged, raised, or persisted.

    Args:
        text (str | None): Text that may contain credentials.
    Returns:
        str | None: The same text with credentials replaced by placeholders.

    """
    if not text:
        return text
    redacted = _URL_CREDENTIAL_PATTERN.sub("://***:***@", text)
    redacted = _KNOWN_TOKEN_PATTERN.sub("***REDACTED-TOKEN***", redacted)
    redacted = _AUTH_HEADER_VALUE_PATTERN.sub(lambda m: f"{m.group(1)} ***REDACTED-TOKEN***", redacted)
    return redacted
