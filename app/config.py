import os

ENV = os.getenv("APP_ENV", "development")
IS_PROD = ENV == "production"


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./ehcc.db").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if IS_PROD:
        raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
    SECRET_KEY = "dev-only-secret-change-me"

SHOW_MOBILE_TO_VIEWERS = os.getenv("SHOW_MOBILE_TO_VIEWERS", "0") == "1"
TIMEZONE = "Asia/Kolkata"
DEFAULT_ROUNDING_STEP = 5
ADMIN_SESSION_HOURS = 12
