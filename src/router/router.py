from fastapi import APIRouter, HTTPException, status
from models.repo_request import RepoRequest
from services.doc_services import analyze_repo
from config.log_config import get_logger
from services.sphinx_services import create_sphinx_setup

logger = get_logger(__name__)

router = APIRouter()

@router.get("/")
async def root():
    logger.info("Root endpoint accessed.")
    return {"message": "Welcome to the Markdown Generator API. Visit /docs for API documentation."}


@router.post("/generate")
async def generate_docs(req: RepoRequest):
    logger.info(f"/generate endpoint called with provider={req.provider}, repo_url={req.repo_url}, branch={req.branch}")
    if not req.repo_url or not req.token or not req.branch or not req.provider:
        logger.warning("Missing required parameters in request.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameters: repo_url, token, branch, or provider."
        )
    try:
        # 1. ANALYZE REPO
        docstring_analysis_file, docstring_analysis = analyze_repo(req.provider, req.repo_url, req.token, req.branch)
        logger.info("Docstring analysis completed successfully.")
        print(docstring_analysis_file)

        # 2. CREATE SPHINX SETUP
        sphinx_setup_created = create_sphinx_setup(req.provider, req.repo_url, req.token, req.branch, docstring_analysis_file)
        if not sphinx_setup_created:
            logger.error("Sphinx setup creation failed.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Sphinx setup creation failed."
            )

        return {
            "status": "success",
            "sphinx_setup_created": sphinx_setup_created,
            "Docstring_analysis": docstring_analysis,
        }
    except ValueError as ve:
        logger.error(f"ValueError: {ve}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve)
        )
    except PermissionError as pe:
        logger.error(f"PermissionError: {pe}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(pe)
        )
    except Exception as e:
        logger.error(f"Unhandled Exception: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred: " + str(e)
        )