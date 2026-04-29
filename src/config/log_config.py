"""
Centralized logging configuration.

Sets up file-based logging with configurable log level and format
(via environment variables). Suppresses noisy logs from `watchfiles`
and `uvicorn`. Use `get_logger(name)` to retrieve a module-specific logger.
"""

import logging
import os
from datetime import datetime

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
RUN_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_LOG_DIR = None
LOG_FILE = None


def _configure_root_logger() -> logging.Logger:
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    if not root_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root_logger.addHandler(stream_handler)
    return root_logger


_ROOT_LOGGER = _configure_root_logger()


def bind_repo_log_dir(repo_log_dir: str) -> str:
    """
    Routes app logs into the active repo run folder.
    """
    global RUN_LOG_DIR, LOG_FILE

    os.makedirs(repo_log_dir, exist_ok=True)
    log_file = os.path.join(repo_log_dir, "app.log")

    for handler in list(_ROOT_LOGGER.handlers):
        if isinstance(handler, logging.FileHandler):
            _ROOT_LOGGER.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    _ROOT_LOGGER.addHandler(file_handler)

    RUN_LOG_DIR = repo_log_dir
    LOG_FILE = log_file
    return log_file

# Suppress logs from 'watchfiles' and 'uvicorn' in app.log
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str):
    return logging.getLogger(name)


def get_run_log_dir() -> str | None:
    return RUN_LOG_DIR
