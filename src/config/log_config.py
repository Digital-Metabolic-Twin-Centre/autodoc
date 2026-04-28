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
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"app_{timestamp}.log")

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=[logging.FileHandler(LOG_FILE)])

# Suppress logs from 'watchfiles' and 'uvicorn' in app.log
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str):
    return logging.getLogger(name)
