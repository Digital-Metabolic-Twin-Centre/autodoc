import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
SQLITE_PATH = os.getenv("ADMIN_SQLITE_PATH", str(DATA_DIR / "admin.db"))
DATABASE_URL = f"sqlite:///{SQLITE_PATH}"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
print(f"Admin username: {ADMIN_USERNAME}")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
print(f"Admin password: {'*' * len(ADMIN_PASSWORD)}")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "")
print(f"Admin secret key: {'*' * len(ADMIN_SECRET_KEY)}")
ADMIN_CSRF_COOKIE = "autodoc_csrf"
ADMIN_SESSION_COOKIE = "autodoc_admin_session"
ADMIN_SESSION_MAX_AGE = int(os.getenv("ADMIN_SESSION_MAX_AGE", str(60 * 60 * 12)))

DEFAULT_OPENAI_MODEL = os.getenv("ADMIN_DEFAULT_MODEL", "gpt-4o-mini")
MAX_ACTIVITY_ITEMS = int(os.getenv("ADMIN_ACTIVITY_ITEMS", "8"))
