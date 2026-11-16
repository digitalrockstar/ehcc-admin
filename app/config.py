import os
from pathlib import Path

from sqlalchemy.engine import URL

ENV = os.getenv("APP_ENV", "development")
IS_PROD = ENV == "production"


def _database_url() -> str:
    """Use an explicitly configured external URL, otherwise a local SQLite file."""
    external_url = os.getenv("DATABASE_URL", "").strip()
    if external_url:
        if external_url.startswith("postgres://"):
            external_url = "postgresql://" + external_url[len("postgres://"):]
        if external_url.startswith("postgresql://"):
            external_url = "postgresql+psycopg://" + external_url[len("postgresql://"):]
        return external_url

    sqlite_path = Path(os.getenv("SQLITE_DB_PATH", "./ehcc.db").strip()).expanduser()
    return URL.create("sqlite", database=str(sqlite_path)).render_as_string(hide_password=False)


DATABASE_URL = _database_url()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if IS_PROD:
        raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
    SECRET_KEY = "dev-only-secret-change-me"

SHOW_MOBILE_TO_VIEWERS = os.getenv("SHOW_MOBILE_TO_VIEWERS", "0") == "1"
APP_BASE_PATH = os.getenv("APP_BASE_PATH", "").strip().rstrip("/")
if APP_BASE_PATH and (not APP_BASE_PATH.startswith("/") or "//" in APP_BASE_PATH or "?" in APP_BASE_PATH or "#" in APP_BASE_PATH):
    raise RuntimeError("APP_BASE_PATH must be an absolute URL path, e.g. /ehcc")

TIMEZONE = "Asia/Kolkata"
DEFAULT_ROUNDING_STEP = 5
ADMIN_SESSION_HOURS = 12
