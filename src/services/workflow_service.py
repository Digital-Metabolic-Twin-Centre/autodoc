import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from config.log_config import get_run_log_dir
from models.repo_request import (
    ArchitectureApprovalRequest,
    ArchitectureGenerationRequest,
    DocstringPullRequestRequest,
    PublishPagesRequest,
    RepoRequest,
)
from services.architecture_services import (
    ArchitectureAnalysisError,
    ArchitectureApprovalError,
    ArchitectureOverwriteRequiredError,
    apply_architecture_approval,
    generate_architecture_draft,
)
from services.doc_services import RepoAnalysisError, analyse_repo
from services.docstring_pr_services import (
    DocstringPullRequestError,
    create_python_docstring_pull_request,
)
from services.sphinx_services import PublishPagesError, create_sphinx_setup, publish_github_pages
from utils.docstring_generation import DEFAULT_OPENAI_MODEL
from utils.git_utils import extract_repo_path
from utils.output_paths import bind_repo_run_log_dir


@dataclass
class WorkflowRunResult:
    response: dict
    summary_output: str
    artifact_dir: str | None = None
    log_path: str | None = None
    source_branch: str | None = None
    published_branch: str | None = None
    documentation_url: str | None = None
    metrics_files_analyzed: int | None = None
    metrics_docstrings_generated: int | None = None
    metrics_skipped_files: int | None = None
    draft_id: str | None = None


def _notify_progress(progress_callback, percent: float, message: str) -> None:
    if progress_callback is not None:
        progress_callback(percent, message)


def _summarize_generate(docstring_analysis: list[dict]) -> tuple[int, int, int]:
    files_analyzed = len(docstring_analysis)
    docstrings_generated = 0
    skipped_files = 0
    for file_summary in docstring_analysis:
        generated_for_file = any(item.get("generated_docstring") for item in file_summary.get("docstring_analysis", []))
        if generated_for_file:
            docstrings_generated += sum(
                1 for item in file_summary.get("docstring_analysis", []) if item.get("generated_docstring")
            )
        else:
            skipped_files += 1
    return files_analyzed, docstrings_generated, skipped_files


def _github_pages_url(repo_url: str) -> str | None:
    repo_path = extract_repo_path(repo_url, "github")
    if "/" not in repo_path:
        return None
    owner, repo_name = repo_path.split("/", 1)
    return f"https://{owner}.github.io/{repo_name}/"


def execute_generate_request(req: RepoRequest, progress_callback=None) -> WorkflowRunResult:
    if not req.repo_url or not req.token or not req.branch or not req.provider:
        raise ValueError("Missing required parameters: repo_url, token, branch, or provider.")

    _notify_progress(progress_callback, 25.0, "Analyzing repository")
    analysis_file, docstring_analysis = analyse_repo(
        req.provider,
        req.repo_url,
        req.token,
        req.branch,
        req.target_folders,
        req.model or DEFAULT_OPENAI_MODEL,
        req.reuse_doc,
    )
    _notify_progress(progress_callback, 70.0, "Building documentation")
    sphinx_setup_created = create_sphinx_setup(
        req.provider,
        req.repo_url,
        req.token,
        req.branch,
        analysis_file,
        req.docstring_threshold,
        req.low_content_min_lines,
    )
    if not sphinx_setup_created:
        raise PermissionError(
            "Sphinx setup creation failed. Token may lack 'write_repository' scope, "
            f"or branch '{req.branch}' is protected."
        )
    _notify_progress(progress_callback, 90.0, "Finalizing results")
    files_analyzed, docstrings_generated, skipped_files = _summarize_generate(docstring_analysis)
    response = {
        "status": "success",
        "sphinx_setup_created": sphinx_setup_created,
        "Docstring_analysis": docstring_analysis,
    }
    artifact_dir = os.path.dirname(analysis_file)
    log_path = os.path.join(artifact_dir, "app.log")
    return WorkflowRunResult(
        response=response,
        summary_output=json.dumps(
            {
                "files_analyzed": files_analyzed,
                "docstrings_generated": docstrings_generated,
                "skipped_files": skipped_files,
            }
        ),
        artifact_dir=artifact_dir,
        log_path=log_path if os.path.exists(log_path) else None,
        source_branch=req.branch,
        metrics_files_analyzed=files_analyzed,
        metrics_docstrings_generated=docstrings_generated,
        metrics_skipped_files=skipped_files,
    )


def execute_docstring_pr_request(req: DocstringPullRequestRequest, progress_callback=None) -> WorkflowRunResult:
    _notify_progress(progress_callback, 25.0, "Preparing docstring suggestions")
    bind_repo_run_log_dir(extract_repo_path(req.repo_url, req.provider), req.provider)
    suggestion_branch = req.suggestion_branch or (
        f"autodocs-docstring-suggestions-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"
    )
    _notify_progress(progress_callback, 70.0, "Creating pull request")
    response = create_python_docstring_pull_request(
        req.provider,
        req.repo_url,
        req.token,
        req.base_branch,
        suggestion_branch,
        req.title,
        req.max_docstrings,
    )
    _notify_progress(progress_callback, 90.0, "Finalizing results")
    artifact_dir = get_run_log_dir()
    log_path = os.path.join(artifact_dir, "app.log") if artifact_dir else None
    return WorkflowRunResult(
        response=response,
        summary_output=json.dumps(
            {
                "files_changed": response.get("files_changed", 0),
                "docstrings_added": response.get("docstrings_added", 0),
                "pull_request_url": response.get("pull_request_url"),
            }
        ),
        artifact_dir=artifact_dir,
        log_path=log_path if log_path and os.path.exists(log_path) else None,
        source_branch=req.base_branch,
        metrics_files_analyzed=response.get("files_changed"),
        metrics_docstrings_generated=response.get("docstrings_added"),
        metrics_skipped_files=0,
    )


def execute_publish_request(req: PublishPagesRequest, progress_callback=None) -> WorkflowRunResult:
    _notify_progress(progress_callback, 25.0, "Preparing publish job")
    bind_repo_run_log_dir(extract_repo_path(req.repo_url, "github"), "github")
    _notify_progress(progress_callback, 70.0, "Publishing GitHub Pages")
    published = publish_github_pages(
        req.repo_url,
        req.branch,
        req.token,
        req.low_content_min_lines,
    )
    if not published:
        raise PermissionError(
            "GitHub Pages publish failed. Ensure the branch contains docs sources and the token can write."
        )
    _notify_progress(progress_callback, 90.0, "Finalizing results")
    response = {
        "status": "success",
        "published_branch": "gh-pages",
        "source_branch": req.branch,
    }
    artifact_dir = get_run_log_dir()
    log_path = os.path.join(artifact_dir, "app.log") if artifact_dir else None
    return WorkflowRunResult(
        response=response,
        summary_output=json.dumps(
            {
                "published_branch": "gh-pages",
                "source_branch": req.branch,
                "documentation_url": _github_pages_url(req.repo_url),
            }
        ),
        artifact_dir=artifact_dir,
        log_path=log_path if log_path and os.path.exists(log_path) else None,
        source_branch=req.branch,
        published_branch="gh-pages",
        documentation_url=_github_pages_url(req.repo_url),
    )


def execute_architecture_generation_request(
    req: ArchitectureGenerationRequest, progress_callback=None
) -> WorkflowRunResult:
    _notify_progress(progress_callback, 15.0, "Analyzing repository architecture")
    result = generate_architecture_draft(
        provider=req.provider,
        repo_url=req.repo_url,
        token=req.token,
        branch=req.branch,
        target_folders=req.target_folders,
        output_path=req.output_path,
        include_diagrams=req.include_diagrams,
        reuse_existing_docs=req.reuse_existing_docs,
        progress_callback=progress_callback,
    )
    _notify_progress(progress_callback, 95.0, "Finalizing architecture draft")
    response = {
        "status": result["status"],
        "draft_id": result["draft_id"],
        "draft_path": result["draft_path"],
        "proposed_output_path": result["proposed_output_path"],
        "sections": result["sections_summary"],
        "gaps": result["gaps"],
        "diagram_paths": result["diagram_paths"],
        "approval_required": True,
        "artifact_dir": result["artifact_dir"],
    }
    artifact_dir = result["artifact_dir"]
    log_path = os.path.join(artifact_dir, "app.log")
    return WorkflowRunResult(
        response=response,
        summary_output=json.dumps(
            {
                "draft_id": result["draft_id"],
                "sections_populated": sum(
                    1 for section in result["sections_summary"] if section["status"] == "populated"
                ),
                "gaps": len(result["gaps"]),
            }
        ),
        artifact_dir=artifact_dir,
        log_path=log_path if os.path.exists(log_path) else None,
        source_branch=req.branch,
        draft_id=result["draft_id"],
    )


def execute_architecture_approval_request(
    req: ArchitectureApprovalRequest, progress_callback=None
) -> WorkflowRunResult:
    _notify_progress(progress_callback, 20.0, "Preparing architecture approval")
    bind_repo_run_log_dir(extract_repo_path(req.repo_url, req.provider), req.provider)
    _notify_progress(progress_callback, 60.0, "Applying approved architecture document")
    result = apply_architecture_approval(
        provider=req.provider,
        repo_url=req.repo_url,
        token=req.token,
        branch=req.branch,
        draft_id=req.draft_id,
        output_path=req.output_path,
        overwrite_existing=req.overwrite_existing,
        approval_note=req.approval_note,
    )
    _notify_progress(progress_callback, 90.0, "Finalizing approval")
    response = {
        "status": result["status"],
        "draft_id": req.draft_id,
        "output_path": result["output_path"],
        "commit_url": result["commit_url"],
        "branch": req.branch,
    }
    artifact_dir = get_run_log_dir()
    log_path = os.path.join(artifact_dir, "app.log") if artifact_dir else None
    return WorkflowRunResult(
        response=response,
        summary_output=json.dumps({"draft_id": req.draft_id, "output_path": result["output_path"]}),
        artifact_dir=artifact_dir,
        log_path=log_path if log_path and os.path.exists(log_path) else None,
        source_branch=req.branch,
        draft_id=req.draft_id,
    )


__all__ = [
    "ArchitectureAnalysisError",
    "ArchitectureApprovalError",
    "ArchitectureOverwriteRequiredError",
    "DocstringPullRequestError",
    "PublishPagesError",
    "RepoAnalysisError",
    "WorkflowRunResult",
    "execute_architecture_approval_request",
    "execute_architecture_generation_request",
    "execute_docstring_pr_request",
    "execute_generate_request",
    "execute_publish_request",
]
