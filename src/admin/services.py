"""
Admin dashboard service layer: form validation, run-request construction,
and run/dashboard data aggregation used by admin/router.py's HTTP handlers.

Kept separate from router.py so route handlers stay thin (parse request,
call a service function, render/redirect) and this logic can be tested and
reused without going through FastAPI request/response plumbing.
"""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from admin.database import SessionLocal
from admin.models import RepositoryConfig, RunRecord
from admin.security import decrypt_token
from admin.settings import DEFAULT_OPENAI_MODEL, MAX_ACTIVITY_ITEMS
from models.repo_request import (
    ArchitectureGenerationRequest,
    DocstringPullRequestRequest,
    PublishPagesRequest,
    RepoRequest,
)
from utils.git_utils import check_repo_url_host, extract_repo_path

DOCSTRING_PR_ENDPOINT = "/suggest-docstrings-pr"
LEGACY_DOCSTRING_PR_ENDPOINT = "/suggest-python-docstrings-pr"

ENDPOINT_LABELS = {
    "/generate": "Generate Docs",
    "/publish-pages": "Publish Pages",
    DOCSTRING_PR_ENDPOINT: "Suggest Docstring PR",
    LEGACY_DOCSTRING_PR_ENDPOINT: "Suggest Docstring PR",
    "/generate-architecture-docs": "Generate Architecture Docs",
    "/approve-architecture-docs": "Approve Architecture Docs",
}
DEFAULT_ARCHITECTURE_OUTPUT_PATH = "docs/project/architecture.rst"
SENSITIVE_PAYLOAD_FIELDS = {"token"}
TOKEN_REQUIRED_ENDPOINTS = {
    "/generate",
    "/publish-pages",
    DOCSTRING_PR_ENDPOINT,
    LEGACY_DOCSTRING_PR_ENDPOINT,
    "/generate-architecture-docs",
    "/approve-architecture-docs",
}


def parse_target_folders(raw_value: str) -> list[str]:
    values = []
    for item in re.split(r"[\n,]+", raw_value or ""):
        normalized = item.strip().strip("\"'").strip().strip("/")
        if not normalized:
            continue
        if normalized.startswith("..") or "/../" in f"/{normalized}/":
            raise HTTPException(status_code=422, detail="Target folders cannot contain '..'.")
        values.append(normalized)
    return values


def validate_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in {"github", "gitlab"}:
        raise HTTPException(status_code=422, detail="Provider must be github or gitlab.")
    return normalized


def validate_repo_form(
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
    if not name.strip():
        raise HTTPException(status_code=422, detail="Repository name is required.")
    if not repo_url.strip():
        raise HTTPException(status_code=422, detail="Repository URL is required.")
    if not default_branch.strip():
        raise HTTPException(status_code=422, detail="Default branch is required.")
    normalized_provider = validate_provider(provider)
    try:
        validated_repo_url = check_repo_url_host(repo_url.strip(), normalized_provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    repo_path = extract_repo_path(validated_repo_url, normalized_provider)
    if docstring_threshold < 0 or docstring_threshold > 1:
        raise HTTPException(status_code=422, detail="Docstring threshold must be between 0 and 1.")
    if low_content_min_lines < 0:
        raise HTTPException(status_code=422, detail="Low content minimum lines must be 0 or greater.")
    return {
        "name": name.strip(),
        "provider": normalized_provider,
        "repo_url": validated_repo_url,
        "repo_path": repo_path,
        "default_branch": default_branch.strip(),
        "target_folders": parse_target_folders(target_folders),
        "preferred_model": preferred_model.strip() or DEFAULT_OPENAI_MODEL,
        "reuse_doc": reuse_doc,
        "docstring_threshold": docstring_threshold,
        "low_content_min_lines": low_content_min_lines,
    }


def safe_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in SENSITIVE_PAYLOAD_FIELDS}


def queue_payload_with_repository_secret(
    endpoint: str,
    payload: dict[str, Any],
    repository: RepositoryConfig | None,
) -> dict[str, Any]:
    if endpoint not in TOKEN_REQUIRED_ENDPOINTS:
        return dict(payload)
    if repository is None:
        raise HTTPException(status_code=422, detail="Run cannot be retried without a repository token.")
    return {
        **payload,
        "token": decrypt_token(repository.encrypted_token),
    }


def build_repo_run_request(
    repository: RepositoryConfig,
    branch: str | None = None,
    target_folders: str | None = None,
    model: str | None = None,
    reuse_doc: bool | None = None,
    docstring_threshold: float | None = None,
    low_content_min_lines: int | None = None,
) -> RepoRequest:
    return RepoRequest(
        provider=repository.provider,
        repo_url=repository.repo_url,
        token=decrypt_token(repository.encrypted_token),
        branch=branch or repository.default_branch,
        target_folders=parse_target_folders(target_folders or ",".join(repository.target_folders)),
        model=(model or repository.preferred_model or DEFAULT_OPENAI_MODEL),
        reuse_doc=repository.reuse_doc if reuse_doc is None else reuse_doc,
        docstring_threshold=repository.docstring_threshold if docstring_threshold is None else docstring_threshold,
        low_content_min_lines=(
            repository.low_content_min_lines if low_content_min_lines is None else low_content_min_lines
        ),
    )


def build_publish_request(
    repository: RepositoryConfig,
    branch: str | None = None,
    low_content_min_lines: int | None = None,
) -> PublishPagesRequest:
    return PublishPagesRequest(
        repo_url=repository.repo_url,
        token=decrypt_token(repository.encrypted_token),
        branch=branch or repository.default_branch,
        low_content_min_lines=(
            repository.low_content_min_lines if low_content_min_lines is None else low_content_min_lines
        ),
    )


def default_suggestion_branch() -> str:
    return f"autodocs-docstring-suggestions-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"


def build_pr_request(
    repository: RepositoryConfig,
    base_branch: str | None,
    suggestion_branch: str | None,
    title: str | None,
    max_docstrings: int,
) -> DocstringPullRequestRequest:
    return DocstringPullRequestRequest(
        provider=repository.provider,
        repo_url=repository.repo_url,
        token=decrypt_token(repository.encrypted_token),
        base_branch=base_branch or repository.default_branch,
        suggestion_branch=(suggestion_branch or default_suggestion_branch()),
        title=(title or "Add suggested docstrings"),
        max_docstrings=max_docstrings,
    )


def build_architecture_generation_request(
    repository: RepositoryConfig,
    branch: str | None = None,
    target_folders: str | None = None,
    output_path: str | None = None,
    include_diagrams: bool = True,
    reuse_existing_docs: bool = True,
) -> ArchitectureGenerationRequest:
    return ArchitectureGenerationRequest(
        provider=repository.provider,
        repo_url=repository.repo_url,
        token=decrypt_token(repository.encrypted_token),
        branch=branch or repository.default_branch,
        target_folders=parse_target_folders(target_folders or ",".join(repository.target_folders)),
        output_path=output_path or DEFAULT_ARCHITECTURE_OUTPUT_PATH,
        include_diagrams=include_diagrams,
        reuse_existing_docs=reuse_existing_docs,
        model=repository.preferred_model or DEFAULT_OPENAI_MODEL,
    )


def create_run_record(
    repository_id: int | None,
    endpoint: str,
    admin_user: str,
    payload: dict[str, Any],
) -> int:
    with SessionLocal() as session:
        run = RunRecord(
            repository_id=repository_id,
            endpoint=endpoint,
            status="queued",
            progress_percent=5.0,
            progress_message="Queued",
            triggered_by=admin_user,
            request_payload=json.dumps(safe_request_payload(payload), default=str, indent=2),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


def unique_repository_name(session: Any, base_name: str) -> str:
    candidate = f"{base_name} (copy)"
    suffix = 2
    while session.scalar(select(RepositoryConfig).where(RepositoryConfig.name == candidate)) is not None:
        candidate = f"{base_name} (copy {suffix})"
        suffix += 1
    return candidate


def artifact_entries(run: RunRecord) -> list[dict[str, str]]:
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


def load_docstring_suggestions(run: RunRecord) -> list[dict[str, Any]]:
    if run.endpoint != "/generate" or not run.artifact_dir:
        return []
    suggestions_path = os.path.join(run.artifact_dir, "suggested_docstrings.json")
    if not os.path.exists(suggestions_path):
        return []
    try:
        with open(suggestions_path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except (OSError, json.JSONDecodeError):
        return []
    return payload.get("suggestions", [])


def load_language_summary(run: RunRecord) -> list[dict[str, Any]]:
    if run.endpoint != "/generate" or not run.result_payload:
        return []
    try:
        payload = json.loads(run.result_payload)
    except json.JSONDecodeError:
        return []
    return payload.get("languages_detected", [])


def run_log_entries(run: RunRecord) -> list[dict[str, str]]:
    entries = artifact_entries(run)
    entries_by_name = {entry["name"]: dict(entry) for entry in entries}
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


def log_snippet(log_path: str | None, limit: int = 80) -> str:
    if not log_path or not os.path.exists(log_path):
        return ""
    with open(log_path, "r", encoding="utf-8", errors="replace") as file_handle:
        lines = file_handle.readlines()
    return "".join(lines[-limit:])


def read_artifact_preview(artifact_path: Path, max_chars: int = 120_000) -> tuple[str, bool]:
    with open(artifact_path, "r", encoding="utf-8", errors="replace") as file_handle:
        content = file_handle.read(max_chars + 1)
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]
    return content, truncated


def dashboard_context() -> dict[str, Any]:
    with SessionLocal() as session:
        total_repositories = session.scalar(select(func.count(RepositoryConfig.id))) or 0
        total_runs = session.scalar(select(func.count(RunRecord.id))) or 0
        successful_runs = session.scalar(select(func.count(RunRecord.id)).where(RunRecord.status == "completed")) or 0
        failed_runs = session.scalar(select(func.count(RunRecord.id)).where(RunRecord.status == "failed")) or 0
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
        repositories = session.scalars(select(RepositoryConfig).order_by(RepositoryConfig.updated_at.desc())).all()
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
