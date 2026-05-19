from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse

from config.log_config import get_logger
from models.repo_request import (
    DocstringPullRequestRequest,
    PublishPagesRequest,
    RepoRequest,
)
from services.workflow_service import (
    DocstringPullRequestError,
    PublishPagesError,
    RepoAnalysisError,
    execute_docstring_pr_request,
    execute_generate_request,
    execute_publish_request,
)
from utils.docstring_generation import DEFAULT_OPENAI_MODEL

logger = get_logger(__name__)

router = APIRouter()


def _default_docstring_suggestion_branch() -> str:
    """
    Generate a default docstring suggestion with a timestamp.

    Returns:
        str: A formatted string containing the prefix 'autodocs-docstring-suggestions-' followed by
        the current timestamp.

    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"autodocs-docstring-suggestions-{timestamp}"


@router.get("/")
async def root():
    logger.info("Root endpoint accessed.")
    return RedirectResponse(url="/admin", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post("/generate")
async def generate_docs(req: RepoRequest):
    logger.info(
        "/generate endpoint called with provider=%s, repo_url=%s, branch=%s, "
        "model=%s, reuse_doc=%s, docstring_threshold=%s, low_content_min_lines=%s",
        req.provider,
        req.repo_url,
        req.branch,
        req.model or DEFAULT_OPENAI_MODEL,
        req.reuse_doc,
        req.docstring_threshold,
        req.low_content_min_lines,
    )
    if not req.repo_url or not req.token or not req.branch or not req.provider:
        logger.warning("Missing required parameters in request.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameters: repo_url, token, branch, or provider.",
        )
    try:
        return execute_generate_request(req).response
    except HTTPException:
        raise
    except RepoAnalysisError as rae:
        logger.error("Repository analysis failed: %s", rae)
        raise HTTPException(status_code=rae.status_code, detail=str(rae))
    except ValueError as ve:
        logger.error(f"ValueError: {ve}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except PermissionError as pe:
        logger.error(f"PermissionError: {pe}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Unhandled Exception: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred: " + str(e),
        )


@router.post("/suggest-python-docstrings-pr")
async def suggest_python_docstrings_pr(req: DocstringPullRequestRequest):
    suggestion_branch = req.suggestion_branch or _default_docstring_suggestion_branch()
    logger.info(
        "/suggest-python-docstrings-pr endpoint called with provider=%s, repo_url=%s, "
        "base_branch=%s, suggestion_branch=%s",
        req.provider,
        req.repo_url,
        req.base_branch,
        suggestion_branch,
    )
    if not req.repo_url or not req.token or not req.base_branch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameters: repo_url, token, or base_branch.",
        )

    try:
        return execute_docstring_pr_request(req.model_copy(update={"suggestion_branch": suggestion_branch})).response
    except DocstringPullRequestError as dpe:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(dpe))
    except Exception as e:
        logger.error(f"Unhandled Exception: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred: " + str(e),
        )


@router.post("/publish-pages")
async def publish_pages(req: PublishPagesRequest):
    logger.info(
        "/publish-pages endpoint called with repo_url=%s, branch=%s, low_content_min_lines=%s",
        req.repo_url,
        req.branch,
        req.low_content_min_lines,
    )
    if not req.repo_url or not req.token or not req.branch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameters: repo_url, token, or branch.",
        )

    try:
        return execute_publish_request(req).response
    except HTTPException:
        raise
    except PublishPagesError as pe:
        raise HTTPException(status_code=pe.status_code, detail=str(pe))
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Unhandled Exception: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred: " + str(e),
        )
