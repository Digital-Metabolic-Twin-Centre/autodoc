from fastapi import APIRouter, HTTPException, status
from models.repo_request import RepoRequest
#from services.doc_service import analyze_repo
from services.doc_services import analyze_repo

router = APIRouter()

@router.get("/")
async def root():
    return {"message": "Welcome to the Markdown Generator API. Visit /docs for API documentation."}

@router.post("/generate")
async def generate_docs(req: RepoRequest):
    if not req.repo_url or not req.token or not req.branch or not req.provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameters: repo_url, token, branch, or provider."
        )
    try:
        #files_missing_docstring, file_present_docstring = analyze_repo(req.provider, req.repo_url, req.token, req.branch)
        docstring_analysis = analyze_repo(req.provider, req.repo_url, req.token, req.branch)
        return {
            "status": "success",
            "Docstring_analysis": docstring_analysis,
            #"files_with_missing_docstring": files_missing_docstring,
            #"files_with_present_docstring": file_present_docstring
        }
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve)
        )
    except PermissionError as pe:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(pe)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred: " + str(e)
        )