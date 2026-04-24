from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from config.log_config import get_logger
from models.repo_request import DocstringPullRequestRequest, PublishPagesRequest, RepoRequest
from services.doc_services import analyze_repo
from services.docstring_pr_services import (
    DocstringPullRequestError,
    create_python_docstring_pull_request,
)
from services.sphinx_services import PublishPagesError, create_sphinx_setup, publish_github_pages

logger = get_logger(__name__)

router = APIRouter()


def _default_docstring_suggestion_branch() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"autodocs/python-docstring-suggestions-{timestamp}"


@router.get("/")
async def root():
    logger.info("Root endpoint accessed.")
    return {"message": "Welcome to the Markdown Generator API. Visit /docs for API documentation."}


@router.post("/generate")
async def generate_docs(req: RepoRequest):
    logger.info(
        "/generate endpoint called with provider=%s, repo_url=%s, branch=%s",
        req.provider,
        req.repo_url,
        req.branch,
    )
    if not req.repo_url or not req.token or not req.branch or not req.provider:
        logger.warning("Missing required parameters in request.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameters: repo_url, token, branch, or provider.",
        )
    try:
        # 1. ANALYZE REPO
        docstring_analysis_file, docstring_analysis = analyze_repo(
            req.provider, req.repo_url, req.token, req.branch
        )
        logger.info("Docstring analysis completed successfully.")
        print(docstring_analysis_file)

        # Check if analysis found any files
        if not docstring_analysis:
            logger.warning("No files were analyzed. Repository may be empty or inaccessible.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "No files found to analyze. Please check repository URL, "
                    "token permissions, and branch name."
                ),
            )

        # 2. CREATE SPHINX SETUP
        sphinx_setup_created = create_sphinx_setup(
            req.provider, req.repo_url, req.token, req.branch, docstring_analysis_file
        )
        if not sphinx_setup_created:
            logger.error("Sphinx setup creation failed.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Sphinx setup creation failed. Token may lack "
                    f"'write_repository' scope, or branch '{req.branch}' is "
                    "protected. Check token permissions and GitLab branch settings."
                ),
            )

        return {
            "status": "success",
            "sphinx_setup_created": sphinx_setup_created,
            "Docstring_analysis": docstring_analysis,
        }
    except HTTPException:
        raise
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


@router.post("/publish-pages")
async def publish_pages(req: PublishPagesRequest):
    logger.info(
        "/publish-pages endpoint called with repo_url=%s, branch=%s",
        req.repo_url,
        req.branch,
    )
    if not req.repo_url or not req.token or not req.branch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameters: repo_url, token, or branch.",
        )

    try:
        published = publish_github_pages(req.repo_url, req.branch, req.token)
        if not published:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "GitHub Pages publish failed. Make sure the selected branch contains "
                    "the docs sources created during review, Sphinx build dependencies "
                    "are installed for the app, and the token can write repository "
                    "contents and manage GitHub Pages."
                ),
            )
        return {
            "status": "success",
            "published_branch": "gh-pages",
            "source_branch": req.branch,
        }
    except HTTPException:
        raise
    except PublishPagesError as pe:
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
        return create_python_docstring_pull_request(
            req.provider,
            req.repo_url,
            req.token,
            req.base_branch,
            suggestion_branch,
            req.title,
            req.max_docstrings,
        )
    except DocstringPullRequestError as dpe:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(dpe))
    except Exception as e:
        logger.error(f"Unhandled Exception: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred: " + str(e),
        )
