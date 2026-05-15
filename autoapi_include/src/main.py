import uvicorn
from fastapi import FastAPI

from config.log_config import get_logger
from router.router import router as docs_router

logger = get_logger(__name__)
app = FastAPI()
app.include_router(docs_router)

logger.info("FastAPI app started and router included.")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
