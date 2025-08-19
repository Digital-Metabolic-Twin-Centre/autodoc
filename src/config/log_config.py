"""
Centralized logging configuration.

Sets up file-based logging with configurable log level and format 
(via environment variables). Suppresses noisy logs from `watchfiles` 
and `uvicorn`. Use `get_logger(name)` to retrieve a module-specific logger.
"""

import logging
import os

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
LOG_FILE = os.getenv('LOG_FILE', 'app.log')

logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE)
    ]
)

# Suppress logs from 'watchfiles' and 'uvicorn' in app.log
logging.getLogger('watchfiles').setLevel(logging.WARNING)
logging.getLogger('uvicorn').setLevel(logging.WARNING)
logging.getLogger('uvicorn.error').setLevel(logging.WARNING)
logging.getLogger('uvicorn.access').setLevel(logging.WARNING)

def get_logger(name: str):
    return logging.getLogger(name)
