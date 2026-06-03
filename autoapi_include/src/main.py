from pathlib import Path

import uvicorn
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)

from fastapi import FastAPI  # noqa: E402

from admin.database import init_db  # noqa: E402
from admin.jobs import reconcile_interrupted_runs  # noqa: E402
from admin.router import router as admin_router  # noqa: E402
from config.log_config import get_logger  # noqa: E402
from router.router import router as docs_router  # noqa: E402

logger = get_logger(__name__)
app = FastAPI()
init_db()
recovered_runs = reconcile_interrupted_runs()
app.include_router(docs_router)
app.include_router(admin_router)

logger.info("FastAPI app started and router included.")
if recovered_runs:
    logger.warning("Recovered %s interrupted admin run(s) after server startup.", recovered_runs)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
