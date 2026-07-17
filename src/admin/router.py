import json
import os
import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from admin.database import SessionLocal
from admin.jobs import enqueue_run, request_run_cancellation
from admin.models import RepositoryConfig, RunRecord
from admin.security import (
    admin_auth_config_error,
    clear_admin_session,
    decrypt_token,
    encrypt_token,
    ensure_csrf_token,
    get_or_create_csrf_token,
    read_admin_session,
    require_admin,
    set_admin_session,
    validate_admin_credentials,
    verify_csrf,
)
from admin.settings import (
    ADMIN_SESSION_COOKIE,
    DATABASE_URL,
    DEFAULT_OPENAI_MODEL,
    MAX_ACTIVITY_ITEMS,
    TEMPLATES_DIR,
)
from models.repo_request import (
    ArchitectureApprovalRequest,
    ArchitectureGenerationRequest,
    DocstringPullRequestRequest,
    PublishPagesRequest,
    RepoRequest,
)
from utils.git_utils import extract_repo_path

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/admin", tags=["admin"])

ENDPOINT_LABELS = {
    "/generate": "Generate Docs",
    "/publish-pages": "Publish Pages",
    "/suggest-python-docstrings-pr": "Suggest Docstring PR",
    "/generate-architecture-docs": "Generate Architecture Docs",
    "/approve-architecture-docs": "Approve Architecture Docs",
}
DEFAULT_ARCHITECTURE_OUTPUT_PATH = "docs/project/architecture.rst"
SENSITIVE_PAYLOAD_FIELDS = {"token"}
TOKEN_REQUIRED_ENDPOINTS = {
    "/generate",
    "/publish-pages",
    "/suggest-python-docstrings-pr",
    "/generate-architecture-docs",
    "/approve-architecture-docs",
}


def _database_label() -> str:
    """
    Format the configured database URL into a human-readable label.

    Returns:
        str: "SQLite (<path>)" if using a SQLite database, otherwise the raw database URL.

    """
    if DATABASE_URL.startswith("sqlite:///"):
        return f"SQLite ({DATABASE_URL.removeprefix('sqlite:///')})"
    return DATABASE_URL


def _json_loads(value: str | None) -> Any:
    """
    Parse a JSON string, returning None for empty or falsy input.

    Args:
        value (str | None): The JSON string to parse, or None/empty.

    Returns:
        Any: The parsed JSON value, or None if `value` is falsy.

    """
    if not value:
        return None
    return json.loads(value)


def _safe_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of the payload with sensitive fields removed.

    Args:
        payload (dict[str, Any]): The original request payload.

    Returns:
        dict[str, Any]: A new dict excluding keys listed in SENSITIVE_PAYLOAD_FIELDS.

    """
    return {
        key: value
        for key, value in payload.items()
        if key not in SENSITIVE_PAYLOAD_FIELDS
    }


def _queue_payload_with_repository_secret(
    endpoint: str,
    payload: dict[str, Any],
    repository: RepositoryConfig | None,
) -> dict[str, Any]:
    """
    Adds the repository's decrypted token to the payload for endpoints that require authentication.

    Args:
        endpoint (str): The API endpoint being called.
        payload (dict[str, Any]): The base payload to send.
        repository (RepositoryConfig | None): Repository config containing the encrypted token, if
        available.

    Returns:
        dict[str, Any]: The payload, augmented with a decrypted token if required.

    Raises:
        HTTPException: If the endpoint requires a token but no repository is provided.

    """
    if endpoint not in TOKEN_REQUIRED_ENDPOINTS:
        return dict(payload)
    if repository is None:
        raise HTTPException(
            status_code=422, detail="Run cannot be retried without a repository token."
        )
    return {
        **payload,
        "token": decrypt_token(repository.encrypted_token),
    }


def _fmt_duration(seconds: float | None) -> str:
    """
    Format a duration in seconds as a human-readable string.

    Args:
        seconds (float | None): Duration in seconds, or None if unavailable.

    Returns:
        str: Formatted duration (e.g., "0.50s", "1.2s", "2m 5s"), or "-" if None.

    """
    if seconds is None:
        return "-"
    if seconds < 1:
        return f"{seconds:.2f}s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}m {remainder}s"


def _status_badge_classes(status_value: str) -> str:
    """
    Return Tailwind CSS classes for styling a status badge based on status value.

    Args:
        status_value (str): The status to style (e.g., "completed", "failed", "cancelled").

    Returns:
        str: Tailwind CSS class names for background and text color, with dark mode variants.

    """
    if status_value == "completed":
        return "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-200"
    if status_value == "failed":
        return "bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-200"
    if status_value == "cancelled":
        return "bg-slate-200 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200"
    return "bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-200"


templates.env.filters["from_json"] = _json_loads
templates.env.filters["duration"] = _fmt_duration
templates.env.filters["status_badge_classes"] = _status_badge_classes


def _is_htmx(request: Request) -> bool:
    """
    Check whether the incoming request was made via HTMX.

    Args:
        request (Request): The incoming HTTP request object.

    Returns:
        bool: True if the request has the 'HX-Request' header set to 'true', False otherwise.

    """
    return request.headers.get("HX-Request") == "true"


def _template_response(
    request: Request,
    name: str,
    context: dict[str, Any],
    status_code: int = 200,
) -> Response:
    """
    Render a Jinja2 template into an HTML response, injecting request context and CSRF token.

    Args:
        request (Request): The incoming HTTP request.
        name (str): Name of the template file to render.
        context (dict[str, Any]): Template context variables.
        status_code (int, optional): HTTP status code for the response. Defaults to 200.

    Returns:
        Response: Rendered HTML response with CSRF cookie/token set.

    """
    context["request"] = request
    context["active_path"] = request.url.path
    csrf_token = get_or_create_csrf_token(request)
    context["csrf_token"] = csrf_token
    context["database_label"] = _database_label()
    content = templates.get_template(name).render(context)
    response = HTMLResponse(content=content, status_code=status_code)
    ensure_csrf_token(request, response, csrf_token)
    return response


def _redirect(url: str, request: Request, status_code: int = 303) -> Response:
    """
    Redirect to a URL, using an HTMX-compatible redirect header if the request came from HTMX.

    Args:
        url (str): The target URL to redirect to.
        request (Request): The incoming HTTP request.
        status_code (int, optional): HTTP status code for non-HTMX redirects. Defaults to 303.

    Returns:
        Response: An HX-Redirect response for HTMX requests, otherwise a RedirectResponse.

    """
    if _is_htmx(request):
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = url
        return response
    return RedirectResponse(url=url, status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    if read_admin_session(request.cookies.get(ADMIN_SESSION_COOKIE)):
        return _redirect("/admin", request)
    context = {
        "page_title": "Admin Sign In",
        "error_message": admin_auth_config_error(),
    }
    return _template_response(request, "admin/login.html", context)


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    _: None = Depends(verify_csrf),
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    try:
        admin_user = validate_admin_credentials(username.strip(), password)
    except ValueError:
        context = {
            "page_title": "Admin Sign In",
            "error_message": "The username or password was not recognized.",
        }
        response = _template_response(
            request, "admin/login.html", context, status_code=401
        )
        clear_admin_session(response)
        return response
    except HTTPException as exc:
        context = {
            "page_title": "Admin Sign In",
            "error_message": str(exc.detail),
        }
        response = _template_response(
            request, "admin/login.html", context, status_code=exc.status_code
        )
        clear_admin_session(response)
        return response

    response = _redirect("/admin", request)
    set_admin_session(response, admin_user)
    ensure_csrf_token(request, response)
    return response


@router.post("/logout")
async def logout(request: Request, _: None = Depends(verify_csrf)) -> Response:
    response = _redirect("/admin/login", request)
    clear_admin_session(response)
    return response


def _parse_target_folders(raw_value: str) -> list[str]:
    """
    Parse and validate target folder paths from a raw delimited string.

    Args:
        raw_value (str): Raw string containing folder paths separated by newlines or commas.

    Returns:
        list[str]: Normalized, non-empty folder paths with quotes and slashes stripped.

    Raises:
        HTTPException: If a folder path contains '..' path traversal segments.

    """
    values = []
    for item in re.split(r"[\n,]+", raw_value or ""):
        normalized = item.strip().strip("\"'").strip().strip("/")
        if not normalized:
            continue
        if normalized.startswith("..") or "/../" in f"/{normalized}/":
            raise HTTPException(
                status_code=422, detail="Target folders cannot contain '..'."
            )
        values.append(normalized)
    return values


def _validate_provider(provider: str) -> str:
    """
    Validate and normalize a repository provider identifier.

    Args:
        provider (str): The provider name to validate.

    Returns:
        str: The normalized provider name ("github" or "gitlab").

    Raises:
        HTTPException: If the provider is not "github" or "gitlab".

    """
    normalized = provider.strip().lower()
    if normalized not in {"github", "gitlab"}:
        raise HTTPException(
            status_code=422, detail="Provider must be github or gitlab."
        )
    return normalized


def _validate_repo_form(
    name: str,
    provider: str,
    repo_url: str,
    default_branch: str,
    target_folders: str,
    preferred_model: str,
    reuse_doc: bool,
    docstring_threshold: float,
    low_content_min_lines: int,
) -> dict[str, Any]:
    """
    Validate and normalize repository configuration form fields, raising HTTPException on invalid
    input.

    Args:
        name (str): Repository display name.
        provider (str): Repository hosting provider identifier.
        repo_url (str): URL of the repository.
        default_branch (str): Default branch name.
        target_folders (str): Comma/newline-separated target folder paths.
        preferred_model (str): Preferred model name, falls back to default if blank.
        reuse_doc (bool): Whether to reuse existing documentation.
        docstring_threshold (float): Minimum docstring coverage ratio (0-1).
        low_content_min_lines (int): Minimum line count threshold for low-content detection.

    Returns:
        dict[str, Any]: Normalized and validated repository configuration values.

    """
    if not name.strip():
        raise HTTPException(status_code=422, detail="Repository name is required.")
    if not repo_url.strip():
        raise HTTPException(status_code=422, detail="Repository URL is required.")
    if not default_branch.strip():
        raise HTTPException(status_code=422, detail="Default branch is required.")
    normalized_provider = _validate_provider(provider)
    repo_path = extract_repo_path(repo_url.strip(), normalized_provider)
    if docstring_threshold < 0 or docstring_threshold > 1:
        raise HTTPException(
            status_code=422, detail="Docstring threshold must be between 0 and 1."
        )
    if low_content_min_lines < 0:
        raise HTTPException(
            status_code=422, detail="Low content minimum lines must be 0 or greater."
        )
    return {
        "name": name.strip(),
        "provider": normalized_provider,
        "repo_url": repo_url.strip(),
        "repo_path": repo_path,
        "default_branch": default_branch.strip(),
        "target_folders": _parse_target_folders(target_folders),
        "preferred_model": preferred_model.strip() or DEFAULT_OPENAI_MODEL,
        "reuse_doc": reuse_doc,
        "docstring_threshold": docstring_threshold,
        "low_content_min_lines": low_content_min_lines,
    }


def _build_repo_run_request(
    repository: RepositoryConfig,
    branch: str | None = None,
    target_folders: str | None = None,
    model: str | None = None,
    reuse_doc: bool | None = None,
    docstring_threshold: float | None = None,
    low_content_min_lines: int | None = None,
) -> RepoRequest:
    """
    Build a RepoRequest from repository config, applying explicit overrides where provided.

    Args:
        repository (RepositoryConfig): Base repository configuration with defaults.
        branch (str | None): Branch override; falls back to repository's default branch.
        target_folders (str | None): Comma-separated folders override; falls back to repository's
        target folders.
        model (str | None): Model override; falls back to preferred or default model.
        reuse_doc (bool | None): Reuse-doc flag override; falls back to repository setting.
        docstring_threshold (float | None): Docstring threshold override; falls back to repository
        setting.
        low_content_min_lines (int | None): Minimum lines override; falls back to repository
        setting.

    Returns:
        RepoRequest: Fully populated request object with overrides applied over repository defaults.

    """
    return RepoRequest(
        provider=repository.provider,
        repo_url=repository.repo_url,
        token=decrypt_token(repository.encrypted_token),
        branch=branch or repository.default_branch,
        target_folders=_parse_target_folders(
            target_folders or ",".join(repository.target_folders)
        ),
        model=(model or repository.preferred_model or DEFAULT_OPENAI_MODEL),
        reuse_doc=repository.reuse_doc if reuse_doc is None else reuse_doc,
        docstring_threshold=repository.docstring_threshold
        if docstring_threshold is None
        else docstring_threshold,
        low_content_min_lines=(
            repository.low_content_min_lines
            if low_content_min_lines is None
            else low_content_min_lines
        ),
    )


def _build_publish_request(
    repository: RepositoryConfig,
    branch: str | None = None,
    low_content_min_lines: int | None = None,
) -> PublishPagesRequest:
    """
    Build a PublishPagesRequest from a repository configuration, decrypting its token and applying
    overrides.

    Args:
        repository (RepositoryConfig): Repository configuration containing URL, encrypted token, and
        defaults.
        branch (str | None): Branch to publish to; falls back to the repository's default branch if
        None.
        low_content_min_lines (int | None): Minimum line count threshold; falls back to the
        repository's configured value if None.

    Returns:
        PublishPagesRequest: The assembled request ready for publishing.

    """
    return PublishPagesRequest(
        repo_url=repository.repo_url,
        token=decrypt_token(repository.encrypted_token),
        branch=branch or repository.default_branch,
        low_content_min_lines=(
            repository.low_content_min_lines
            if low_content_min_lines is None
            else low_content_min_lines
        ),
    )


def _default_suggestion_branch() -> str:
    """
    Generate a default branch name for docstring suggestions using the current UTC timestamp.

    Returns:
        str: Branch name in the format 'autodocs-docstring-suggestions-YYYYMMDD-HHMM'.

    """
    return f"autodocs-docstring-suggestions-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"


def _build_pr_request(
    repository: RepositoryConfig,
    base_branch: str | None,
    suggestion_branch: str | None,
    title: str | None,
    max_docstrings: int,
) -> DocstringPullRequestRequest:
    """
    Build a docstring pull request request payload from repository configuration and optional
    overrides.

    Args:
        repository (RepositoryConfig): Repository configuration containing provider, URL, encrypted
        token, and default branch.
        base_branch (str | None): Base branch to target; falls back to repository's default branch.
        suggestion_branch (str | None): Branch name for suggestions; falls back to a generated
        default.
        title (str | None): Pull request title; falls back to a default title.
        max_docstrings (int): Maximum number of docstrings to include.

    Returns:
        DocstringPullRequestRequest: The constructed pull request request object.

    """
    return DocstringPullRequestRequest(
        provider=repository.provider,
        repo_url=repository.repo_url,
        token=decrypt_token(repository.encrypted_token),
        base_branch=base_branch or repository.default_branch,
        suggestion_branch=(suggestion_branch or _default_suggestion_branch()),
        title=(title or "Add suggested docstrings"),
        max_docstrings=max_docstrings,
    )


def _build_architecture_generation_request(
    repository: RepositoryConfig,
    branch: str | None = None,
    target_folders: str | None = None,
    output_path: str | None = None,
    include_diagrams: bool = True,
    reuse_existing_docs: bool = True,
) -> ArchitectureGenerationRequest:
    """
    Build an ArchitectureGenerationRequest by combining repository defaults with optional overrides.

    Args:
        repository (RepositoryConfig): Repository configuration providing default values.
        branch (str | None): Branch to use; defaults to the repository's default branch.
        target_folders (str | None): Comma-separated folders to target; defaults to the repository's
        configured folders.
        output_path (str | None): Output path for generated docs; defaults to
        DEFAULT_ARCHITECTURE_OUTPUT_PATH.
        include_diagrams (bool): Whether to include diagrams in the output.
        reuse_existing_docs (bool): Whether to reuse existing documentation.

    Returns:
        ArchitectureGenerationRequest: The fully populated request object.

    """
    return ArchitectureGenerationRequest(
        provider=repository.provider,
        repo_url=repository.repo_url,
        token=decrypt_token(repository.encrypted_token),
        branch=branch or repository.default_branch,
        target_folders=_parse_target_folders(
            target_folders or ",".join(repository.target_folders)
        ),
        output_path=output_path or DEFAULT_ARCHITECTURE_OUTPUT_PATH,
        include_diagrams=include_diagrams,
        reuse_existing_docs=reuse_existing_docs,
        model=repository.preferred_model or DEFAULT_OPENAI_MODEL,
    )


def _artifact_entries(run: RunRecord) -> list[dict[str, str]]:
    """
    Collect metadata for files stored in a run's artifact directory.

    Args:
        run (RunRecord): Run record containing the artifact directory path.

    Returns:
        list[dict[str, str]]: List of dicts with "name" and "size" for each file found, or an empty
        list if the directory is missing.

    """
    artifact_dir = run.artifact_dir
    if not artifact_dir or not os.path.isdir(artifact_dir):
        return []
    entries = []
    for name in sorted(os.listdir(artifact_dir)):
        file_path = os.path.join(artifact_dir, name)
        if os.path.isfile(file_path):
            entries.append(
                {
                    "name": name,
                    "size": str(os.path.getsize(file_path)),
                }
            )
    return entries


def _run_log_entries(run: RunRecord) -> list[dict[str, str]]:
    """
    Collect and order log-related artifact entries for a run, prioritizing key log files.

    Args:
        run (RunRecord): The run record containing artifacts and an optional log path.

    Returns:
        list[dict[str, str]]: Ordered list of log entry dicts, each with a "label" key, sorted by
        priority then name.

    """
    artifact_entries = _artifact_entries(run)
    entries_by_name = {entry["name"]: dict(entry) for entry in artifact_entries}
    prioritized_names = [
        "app.log",
        "sphinx_build.log",
        "sphinx_publish_fallback.txt",
        "skipped_autoapi_files.txt",
    ]

    if run.log_path and os.path.exists(run.log_path):
        log_name = os.path.basename(run.log_path)
        entries_by_name.setdefault(
            log_name,
            {
                "name": log_name,
                "size": str(os.path.getsize(run.log_path)),
            },
        )

    ordered: list[dict[str, str]] = []
    for name in prioritized_names:
        if name in entries_by_name:
            entry = entries_by_name.pop(name)
            entry["label"] = name
            ordered.append(entry)

    for name in sorted(entries_by_name):
        if not (name.endswith(".log") or name.endswith(".txt")):
            continue
        entry = entries_by_name[name]
        entry["label"] = name
        ordered.append(entry)

    return ordered


def _log_snippet(log_path: str | None, limit: int = 80) -> str:
    """
    Read the last lines of a log file, if it exists.

    Args:
        log_path (str | None): Path to the log file, or None.
        limit (int, optional): Maximum number of trailing lines to return. Defaults to 80.

    Returns:
        str: The last `limit` lines of the file joined together, or an empty string if the path is
        missing or invalid.

    """
    if not log_path or not os.path.exists(log_path):
        return ""
    with open(log_path, "r", encoding="utf-8", errors="replace") as file_handle:
        lines = file_handle.readlines()
    return "".join(lines[-limit:])


def _read_artifact_preview(
    artifact_path: Path, max_chars: int = 120_000
) -> tuple[str, bool]:
    """
    Reads a text artifact file up to a maximum character limit, indicating if it was truncated.

    Args:
        artifact_path (Path): Path to the artifact file to read.
        max_chars (int, optional): Maximum number of characters to read. Defaults to 120,000.

    Returns:
        tuple[str, bool]: The file content (possibly truncated) and a flag indicating whether
        truncation occurred.

    """
    with open(artifact_path, "r", encoding="utf-8", errors="replace") as file_handle:
        content = file_handle.read(max_chars + 1)
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]
    return content, truncated


def _dashboard_context() -> dict[str, Any]:
    """
    Aggregate dashboard statistics and recent activity data for rendering the home view.

    Args:
        None.

    Returns:
        dict[str, Any]: Contains "stats" (counts of repositories, runs, successes, failures, and
        architecture drafts), "recent_runs" (latest RunRecord entries with repository preloaded),
        "repositories" (all RepositoryConfig entries), and "endpoint_labels".

    """
    with SessionLocal() as session:
        total_repositories = (
            session.scalar(select(func.count(RepositoryConfig.id))) or 0
        )
        total_runs = session.scalar(select(func.count(RunRecord.id))) or 0
        successful_runs = (
            session.scalar(
                select(func.count(RunRecord.id)).where(RunRecord.status == "completed")
            )
            or 0
        )
        failed_runs = (
            session.scalar(
                select(func.count(RunRecord.id)).where(RunRecord.status == "failed")
            )
            or 0
        )
        architecture_drafts_generated = (
            session.scalar(
                select(func.count(RunRecord.id)).where(
                    RunRecord.endpoint == "/generate-architecture-docs",
                    RunRecord.status == "completed",
                )
            )
            or 0
        )
        recent_runs = session.scalars(
            select(RunRecord)
            .order_by(RunRecord.created_at.desc())
            .options(selectinload(RunRecord.repository))
            .limit(MAX_ACTIVITY_ITEMS)
        ).all()
        repositories = session.scalars(
            select(RepositoryConfig).order_by(RepositoryConfig.updated_at.desc())
        ).all()
    return {
        "stats": {
            "total_repositories": total_repositories,
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
            "architecture_drafts_generated": architecture_drafts_generated,
        },
        "recent_runs": recent_runs,
        "repositories": repositories,
        "endpoint_labels": ENDPOINT_LABELS,
    }


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request, admin_user: str = Depends(require_admin)
) -> Response:
    context = _dashboard_context()
    context["admin_user"] = admin_user
    return _template_response(request, "admin/dashboard.html", context)


@router.get("/activity", response_class=HTMLResponse)
async def recent_activity_fragment(
    request: Request,
    admin_user: str = Depends(require_admin),
) -> Response:
    context = _dashboard_context()
    context["admin_user"] = admin_user
    return _template_response(request, "admin/partials/activity_feed.html", context)


@router.get("/repositories", response_class=HTMLResponse)
async def repositories_page(
    request: Request, admin_user: str = Depends(require_admin)
) -> Response:
    with SessionLocal() as session:
        repositories = session.scalars(
            select(RepositoryConfig).order_by(RepositoryConfig.updated_at.desc())
        ).all()
    context = {
        "repositories": repositories,
        "admin_user": admin_user,
        "repository": None,
    }
    return _template_response(request, "admin/repositories/index.html", context)


@router.get("/repositories/new", response_class=HTMLResponse)
async def repository_new_form(
    request: Request, admin_user: str = Depends(require_admin)
) -> Response:
    context = {
        "admin_user": admin_user,
        "repository": None,
    }
    return _template_response(request, "admin/repositories/form.html", context)


@router.post("/repositories", response_class=HTMLResponse)
async def create_repository(
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    name: str = Form(...),
    provider: str = Form(...),
    repo_url: str = Form(...),
    default_branch: str = Form(...),
    target_folders: str = Form(default=""),
    preferred_model: str = Form(default=DEFAULT_OPENAI_MODEL),
    reuse_doc: bool = Form(default=False),
    docstring_threshold: float = Form(default=0.5),
    low_content_min_lines: int = Form(default=4),
    token: str = Form(...),
) -> Response:
    data = _validate_repo_form(
        name,
        provider,
        repo_url,
        default_branch,
        target_folders,
        preferred_model,
        reuse_doc,
        docstring_threshold,
        low_content_min_lines,
    )
    if not token.strip():
        raise HTTPException(status_code=422, detail="Access token is required.")

    with SessionLocal() as session:
        existing = session.scalar(
            select(RepositoryConfig).where(RepositoryConfig.name == data["name"])
        )
        if existing:
            raise HTTPException(
                status_code=409, detail="Repository name already exists."
            )
        repository = RepositoryConfig(
            name=data["name"],
            provider=data["provider"],
            repo_url=data["repo_url"],
            repo_path=data["repo_path"],
            default_branch=data["default_branch"],
            preferred_model=data["preferred_model"],
            reuse_doc=data["reuse_doc"],
            docstring_threshold=data["docstring_threshold"],
            low_content_min_lines=data["low_content_min_lines"],
            encrypted_token=encrypt_token(token.strip()),
            token_last4=token.strip()[-4:],
        )
        repository.target_folders = data["target_folders"]
        session.add(repository)
        session.commit()
        session.refresh(repository)

    return _redirect(f"/admin/repositories/{repository.id}", request)


@router.get("/repositories/{repository_id}", response_class=HTMLResponse)
async def repository_detail(
    repository_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
) -> Response:
    with SessionLocal() as session:
        repository = session.get(RepositoryConfig, repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Repository not found.")
        runs = session.scalars(
            select(RunRecord)
            .where(RunRecord.repository_id == repository_id)
            .order_by(RunRecord.created_at.desc())
            .limit(10)
        ).all()
    context = {
        "repository": repository,
        "recent_runs": runs,
        "endpoint_labels": ENDPOINT_LABELS,
        "admin_user": admin_user,
    }
    return _template_response(request, "admin/repositories/detail.html", context)


@router.get("/repositories/{repository_id}/edit", response_class=HTMLResponse)
async def repository_edit_form(
    repository_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
) -> Response:
    with SessionLocal() as session:
        repository = session.get(RepositoryConfig, repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Repository not found.")
    context = {
        "repository": repository,
        "admin_user": admin_user,
    }
    return _template_response(request, "admin/repositories/form.html", context)


@router.post("/repositories/{repository_id}", response_class=HTMLResponse)
async def update_repository(
    repository_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    name: str = Form(...),
    provider: str = Form(...),
    repo_url: str = Form(...),
    default_branch: str = Form(...),
    target_folders: str = Form(default=""),
    preferred_model: str = Form(default=DEFAULT_OPENAI_MODEL),
    reuse_doc: bool = Form(default=False),
    docstring_threshold: float = Form(default=0.5),
    low_content_min_lines: int = Form(default=4),
    token: str = Form(default=""),
) -> Response:
    data = _validate_repo_form(
        name,
        provider,
        repo_url,
        default_branch,
        target_folders,
        preferred_model,
        reuse_doc,
        docstring_threshold,
        low_content_min_lines,
    )
    with SessionLocal() as session:
        repository = session.get(RepositoryConfig, repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Repository not found.")
        repository.name = data["name"]
        repository.provider = data["provider"]
        repository.repo_url = data["repo_url"]
        repository.repo_path = data["repo_path"]
        repository.default_branch = data["default_branch"]
        repository.target_folders = data["target_folders"]
        repository.preferred_model = data["preferred_model"]
        repository.reuse_doc = data["reuse_doc"]
        repository.docstring_threshold = data["docstring_threshold"]
        repository.low_content_min_lines = data["low_content_min_lines"]
        if token.strip():
            repository.encrypted_token = encrypt_token(token.strip())
            repository.token_last4 = token.strip()[-4:]
        session.add(repository)
        session.commit()
    return _redirect(f"/admin/repositories/{repository_id}", request)


@router.post("/repositories/{repository_id}/delete", response_class=HTMLResponse)
async def delete_repository(
    repository_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
) -> Response:
    with SessionLocal() as session:
        repository = session.get(RepositoryConfig, repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Repository not found.")
        session.delete(repository)
        session.commit()
    return _redirect("/admin/repositories", request)


def _create_run_record(
    repository_id: int | None,
    endpoint: str,
    admin_user: str,
    payload: dict[str, Any],
) -> int:
    """
    Create and persist a new run record in the database with an initial queued status.

    Args:
        repository_id (int | None): ID of the associated repository, if any.
        endpoint (str): The endpoint or operation the run corresponds to.
        admin_user (str): Identifier of the user who triggered the run.
        payload (dict[str, Any]): Request payload to sanitize and store with the run.

    Returns:
        int: The ID of the newly created run record.

    """
    with SessionLocal() as session:
        run = RunRecord(
            repository_id=repository_id,
            endpoint=endpoint,
            status="queued",
            progress_percent=5.0,
            progress_message="Queued",
            triggered_by=admin_user,
            request_payload=json.dumps(
                _safe_request_payload(payload), default=str, indent=2
            ),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


@router.post("/repositories/{repository_id}/generate", response_class=HTMLResponse)
async def trigger_generate(
    repository_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    branch: str = Form(default=""),
    target_folders: str = Form(default=""),
    preferred_model: str = Form(default=""),
    reuse_doc: bool = Form(default=False),
    docstring_threshold: float = Form(default=0.5),
    low_content_min_lines: int = Form(default=4),
) -> Response:
    with SessionLocal() as session:
        repository = session.get(RepositoryConfig, repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Repository not found.")
        repo_request = _build_repo_run_request(
            repository,
            branch=branch or repository.default_branch,
            target_folders=target_folders or ",".join(repository.target_folders),
            model=preferred_model or repository.preferred_model,
            reuse_doc=reuse_doc,
            docstring_threshold=docstring_threshold,
            low_content_min_lines=low_content_min_lines,
        )
    run_id = _create_run_record(
        repository_id, "/generate", admin_user, repo_request.model_dump()
    )
    enqueue_run(run_id, "/generate", repo_request.model_dump())
    return _redirect(f"/admin/runs/{run_id}", request)


@router.post("/repositories/{repository_id}/publish", response_class=HTMLResponse)
async def trigger_publish(
    repository_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    branch: str = Form(default=""),
    low_content_min_lines: int = Form(default=4),
) -> Response:
    with SessionLocal() as session:
        repository = session.get(RepositoryConfig, repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Repository not found.")
        publish_request = _build_publish_request(
            repository,
            branch=branch or repository.default_branch,
            low_content_min_lines=low_content_min_lines,
        )
    run_id = _create_run_record(
        repository_id, "/publish-pages", admin_user, publish_request.model_dump()
    )
    enqueue_run(run_id, "/publish-pages", publish_request.model_dump())
    return _redirect(f"/admin/runs/{run_id}", request)


@router.post("/repositories/{repository_id}/suggest-pr", response_class=HTMLResponse)
async def trigger_suggest_pr(
    repository_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    base_branch: str = Form(default=""),
    suggestion_branch: str = Form(default=""),
    title: str = Form(default="Add suggested docstrings"),
    max_docstrings: int = Form(default=50),
) -> Response:
    with SessionLocal() as session:
        repository = session.get(RepositoryConfig, repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Repository not found.")
        if repository.provider != "github":
            raise HTTPException(
                status_code=422,
                detail="Docstring suggestion PRs currently support GitHub only.",
            )
        pr_request = _build_pr_request(
            repository,
            base_branch=base_branch,
            suggestion_branch=suggestion_branch,
            title=title,
            max_docstrings=max_docstrings,
        )
    run_id = _create_run_record(
        repository_id,
        "/suggest-python-docstrings-pr",
        admin_user,
        pr_request.model_dump(),
    )
    enqueue_run(run_id, "/suggest-python-docstrings-pr", pr_request.model_dump())
    return _redirect(f"/admin/runs/{run_id}", request)


@router.post(
    "/repositories/{repository_id}/generate-architecture-docs",
    response_class=HTMLResponse,
)
async def trigger_generate_architecture_docs(
    repository_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    branch: str = Form(default=""),
    target_folders: str = Form(default=""),
    output_path: str = Form(default=DEFAULT_ARCHITECTURE_OUTPUT_PATH),
    include_diagrams: bool = Form(default=True),
    reuse_existing_docs: bool = Form(default=True),
) -> Response:
    with SessionLocal() as session:
        repository = session.get(RepositoryConfig, repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Repository not found.")
        architecture_request = _build_architecture_generation_request(
            repository,
            branch=branch or repository.default_branch,
            target_folders=target_folders or ",".join(repository.target_folders),
            output_path=output_path,
            include_diagrams=include_diagrams,
            reuse_existing_docs=reuse_existing_docs,
        )
    run_id = _create_run_record(
        repository_id,
        "/generate-architecture-docs",
        admin_user,
        architecture_request.model_dump(exclude={"token"}),
    )
    enqueue_run(
        run_id, "/generate-architecture-docs", architecture_request.model_dump()
    )
    return _redirect(f"/admin/runs/{run_id}", request)


@router.post("/runs/{run_id}/approve-architecture-docs", response_class=HTMLResponse)
async def trigger_approve_architecture_docs(
    run_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    overwrite_existing: bool = Form(default=False),
    approval_note: str = Form(default=""),
) -> Response:
    with SessionLocal() as session:
        stmt = (
            select(RunRecord)
            .where(RunRecord.id == run_id)
            .options(selectinload(RunRecord.repository))
        )
        run = session.scalars(stmt).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if run.endpoint != "/generate-architecture-docs" or run.repository is None:
            raise HTTPException(status_code=422, detail="This run cannot be approved.")
        result_payload = _json_loads(run.result_payload)
        if not result_payload or not result_payload.get("draft_id"):
            raise HTTPException(
                status_code=422, detail="No architecture draft is available to approve."
            )
        repository = run.repository
        approval_request = ArchitectureApprovalRequest(
            provider=repository.provider,
            repo_url=repository.repo_url,
            token=decrypt_token(repository.encrypted_token),
            branch=run.source_branch or repository.default_branch,
            draft_id=result_payload["draft_id"],
            output_path=result_payload.get(
                "proposed_output_path", DEFAULT_ARCHITECTURE_OUTPUT_PATH
            ),
            overwrite_existing=overwrite_existing,
            approval_note=approval_note or None,
        )
        repository_id = repository.id
    new_run_id = _create_run_record(
        repository_id,
        "/approve-architecture-docs",
        admin_user,
        approval_request.model_dump(exclude={"token"}),
    )
    enqueue_run(new_run_id, "/approve-architecture-docs", approval_request.model_dump())
    return _redirect(f"/admin/runs/{new_run_id}", request)


@router.get("/runs", response_class=HTMLResponse)
async def runs_page(
    request: Request,
    repository_id: int | None = Query(default=None),
    admin_user: str = Depends(require_admin),
) -> Response:
    with SessionLocal() as session:
        repositories = session.scalars(
            select(RepositoryConfig).order_by(RepositoryConfig.name.asc())
        ).all()
        query = (
            select(RunRecord)
            .order_by(RunRecord.created_at.desc())
            .options(selectinload(RunRecord.repository))
        )
        if repository_id:
            query = query.where(RunRecord.repository_id == repository_id)
        runs = session.scalars(query.limit(100)).all()
    context = {
        "runs": runs,
        "repositories": repositories,
        "selected_repository_id": repository_id,
        "endpoint_labels": ENDPOINT_LABELS,
        "admin_user": admin_user,
    }
    return _template_response(request, "admin/runs/index.html", context)


@router.post("/runs/clear", response_class=HTMLResponse)
async def clear_runs(
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    repository_id: int | None = Form(default=None),
) -> Response:
    del admin_user
    with SessionLocal() as session:
        query = select(RunRecord)
        if repository_id is not None:
            query = query.where(RunRecord.repository_id == repository_id)
        runs = session.scalars(query).all()
        for run in runs:
            session.delete(run)
        session.commit()

    redirect_url = "/admin/runs"
    if repository_id is not None:
        redirect_url = f"/admin/runs?repository_id={repository_id}"
    return _redirect(redirect_url, request)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(
    run_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
) -> Response:
    with SessionLocal() as session:
        stmt = (
            select(RunRecord)
            .where(RunRecord.id == run_id)
            .options(selectinload(RunRecord.repository))
        )
        run = session.scalars(stmt).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
    context = {
        "run": run,
        "endpoint_labels": ENDPOINT_LABELS,
        "artifacts": _artifact_entries(run),
        "run_logs": _run_log_entries(run),
        "log_snippet": _log_snippet(run.log_path),
        "admin_user": admin_user,
    }
    return _template_response(request, "admin/runs/detail.html", context)


@router.get("/runs/{run_id}/status", response_class=HTMLResponse)
async def run_status_fragment(
    run_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
) -> Response:
    with SessionLocal() as session:
        stmt = (
            select(RunRecord)
            .where(RunRecord.id == run_id)
            .options(selectinload(RunRecord.repository))
        )
        run = session.scalars(stmt).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
    context = {
        "run": run,
        "endpoint_labels": ENDPOINT_LABELS,
        "admin_user": admin_user,
    }
    return _template_response(request, "admin/partials/run_status.html", context)


@router.get("/runs/{run_id}/row", response_class=HTMLResponse)
async def run_row_fragment(
    run_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
) -> Response:
    with SessionLocal() as session:
        stmt = (
            select(RunRecord)
            .where(RunRecord.id == run_id)
            .options(selectinload(RunRecord.repository))
        )
        run = session.scalars(stmt).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
    context = {
        "run": run,
        "endpoint_labels": ENDPOINT_LABELS,
        "admin_user": admin_user,
    }
    return _template_response(request, "admin/partials/run_row.html", context)


@router.post("/runs/{run_id}/retry", response_class=HTMLResponse)
async def retry_run(
    run_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
) -> Response:
    with SessionLocal() as session:
        stmt = (
            select(RunRecord)
            .where(RunRecord.id == run_id)
            .options(selectinload(RunRecord.repository))
        )
        run = session.scalars(stmt).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        payload = _json_loads(run.request_payload)
        if payload is None:
            raise HTTPException(status_code=422, detail="Run payload is unavailable.")
        repository_id = run.repository_id
        endpoint = run.endpoint
        queue_payload = _queue_payload_with_repository_secret(
            endpoint, payload, run.repository
        )
    new_run_id = _create_run_record(repository_id, endpoint, admin_user, payload)
    if endpoint == "/generate":
        repo_request = RepoRequest(**queue_payload)
        enqueue_run(new_run_id, "/generate", repo_request.model_dump())
    elif endpoint == "/publish-pages":
        publish_request = PublishPagesRequest(**queue_payload)
        enqueue_run(new_run_id, "/publish-pages", publish_request.model_dump())
    elif endpoint == "/suggest-python-docstrings-pr":
        pr_request = DocstringPullRequestRequest(**queue_payload)
        enqueue_run(
            new_run_id, "/suggest-python-docstrings-pr", pr_request.model_dump()
        )
    else:
        raise HTTPException(status_code=422, detail="Run type is not retryable.")
    return _redirect(f"/admin/runs/{new_run_id}", request)


@router.post("/runs/{run_id}/cancel", response_class=HTMLResponse)
async def cancel_run(
    run_id: int,
    request: Request,
    admin_user: str = Depends(require_admin),
    _: None = Depends(verify_csrf),
    fragment: str = Form(default="redirect"),
) -> Response:
    del admin_user
    try:
        outcome = request_run_cancellation(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Run not found.")

    if outcome not in {"queued", "running", "cancelled"}:
        raise HTTPException(
            status_code=422, detail="Only queued or running runs can be cancelled."
        )

    if _is_htmx(request):
        with SessionLocal() as session:
            stmt = (
                select(RunRecord)
                .where(RunRecord.id == run_id)
                .options(selectinload(RunRecord.repository))
            )
            run = session.scalars(stmt).first()
            if run is None:
                raise HTTPException(status_code=404, detail="Run not found.")
        context = {
            "run": run,
            "endpoint_labels": ENDPOINT_LABELS,
            "admin_user": "",
        }
        if fragment == "row":
            return _template_response(request, "admin/partials/run_row.html", context)
        return _template_response(request, "admin/partials/run_status.html", context)

    return _redirect(f"/admin/runs/{run_id}", request)


@router.get("/runs/{run_id}/artifacts/{artifact_name}")
async def download_artifact(
    run_id: int,
    artifact_name: str,
    request: Request,
    admin_user: str = Depends(require_admin),
) -> Response:
    with SessionLocal() as session:
        stmt = select(RunRecord).where(RunRecord.id == run_id)
        run = session.scalars(stmt).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
    artifact_dir = Path(run.artifact_dir or "")
    target = (artifact_dir / artifact_name).resolve()
    if not artifact_dir or not str(target).startswith(str(artifact_dir.resolve())):
        raise HTTPException(status_code=403, detail="Artifact path is invalid.")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return FileResponse(path=str(target), filename=artifact_name)


@router.get(
    "/runs/{run_id}/artifacts/{artifact_name}/preview", response_class=HTMLResponse
)
async def preview_artifact(
    run_id: int,
    artifact_name: str,
    request: Request,
    admin_user: str = Depends(require_admin),
) -> Response:
    del request, admin_user
    with SessionLocal() as session:
        stmt = select(RunRecord).where(RunRecord.id == run_id)
        run = session.scalars(stmt).first()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
    artifact_dir = Path(run.artifact_dir or "")
    target = (artifact_dir / artifact_name).resolve()
    if not artifact_dir or not str(target).startswith(str(artifact_dir.resolve())):
        raise HTTPException(status_code=403, detail="Artifact path is invalid.")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")

    content, truncated = _read_artifact_preview(target)
    escaped_content = escape(content)
    truncated_note = (
        '<p class="mb-3 text-xs text-amber-600 dark:text-amber-300">'
        "Preview truncated for readability. Download the file for the complete contents."
        "</p>"
        if truncated
        else ""
    )
    html = (
        f'<div class="flex items-center justify-between gap-4">'
        f'<div><h3 class="text-lg font-semibold">{escape(artifact_name)}</h3>'
        f'<p class="text-sm text-slate-500 dark:text-slate-400">{target}</p></div>'
        f'<a href="/admin/runs/{run_id}/artifacts/{escape(artifact_name)}" '
        f'class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium '
        f'text-slate-700 dark:border-slate-700 dark:text-slate-200">Download</a></div>'
        f'<div class="mt-4 rounded-xl bg-slate-950 p-4 text-xs text-slate-100">'
        f'{truncated_note}<pre class="overflow-x-auto whitespace-pre-wrap">{escaped_content}</pre></div>'
    )
    return HTMLResponse(content=html)
