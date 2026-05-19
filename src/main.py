from pathlib import Path

import uvicorn
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)

from fastapi import FastAPI

from admin.database import init_db
from admin.router import router as admin_router
from config.log_config import get_logger
from router.router import router as docs_router

logger = get_logger(__name__)
app = FastAPI()
init_db()
app.include_router(docs_router)
app.include_router(admin_router)

logger.info("FastAPI app started and router included.")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
