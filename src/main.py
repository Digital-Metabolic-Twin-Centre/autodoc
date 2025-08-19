
from fastapi import FastAPI
from router.router import router as docs_router
from config.log_config import get_logger


logger = get_logger(__name__)
app = FastAPI()
app.include_router(docs_router)
logger.info('FastAPI app started and router included.')