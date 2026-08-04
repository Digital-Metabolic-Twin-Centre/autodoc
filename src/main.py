import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from admin.database import init_db  # noqa: E402
from admin.jobs import reconcile_interrupted_runs  # noqa: E402
from admin.router import router as admin_router  # noqa: E402
from config.log_config import get_logger  # noqa: E402
from router.router import router as docs_router  # noqa: E402

logger = get_logger(__name__)


def _env_list(name: str, default: str) -> list[str]:
    """
    Parse a comma-separated environment variable into a list, dropping blanks.

    Args:
        name (str): Environment variable name. default (str): Fallback raw value when unset.
    Returns:
        list[str]: Parsed, trimmed, non-empty entries.

    """
    raw_value = os.getenv(name, default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


# No reverse proxy hostname is known at build time, so default to "*" (unrestricted)
# to avoid breaking deployments; set AUTODOC_ALLOWED_HOSTS to lock this down.
ALLOWED_HOSTS = _env_list("AUTODOC_ALLOWED_HOSTS", "*")
# The admin UI is same-origin (served by this app) and the public API is
# consumed via API-key header, not browser cookies, so cross-origin browser
# access isn't needed by default. Set AUTODOC_CORS_ORIGINS to opt specific
# origins in (e.g. for a decoupled frontend).
CORS_ALLOWED_ORIGINS = _env_list("AUTODOC_CORS_ORIGINS", "")

app = FastAPI()
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
init_db()
recovered_runs = reconcile_interrupted_runs()
app.include_router(docs_router)
app.include_router(admin_router)

logger.info("FastAPI app started and router included.")
if recovered_runs:
    logger.warning("Recovered %s interrupted admin run(s) after server startup.", recovered_runs)

if __name__ == "__main__":  # pragma: no cover
    # Binding all interfaces is required to be reachable inside the Docker container; see Dockerfile/docker-compose.
    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
