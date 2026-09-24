import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import config
from .db import SessionLocal
from .routers import auth, dashboard, players, settings, transactions
from .security import LoginRequired
from .services.ledger import LedgerError
from .services.masters import ensure_defaults
from .web import page

log = logging.getLogger("ehcc")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        with SessionLocal() as db:
            ensure_defaults(db)
    except Exception:  # tables missing before the first migration
        log.exception("Could not seed defaults. Run `alembic upgrade head`.")
    yield


app = FastAPI(title="EHCC Expense Tracker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, max_age=14 * 24 * 3600,
                   same_site="lax", https_only=config.IS_PROD, session_cookie="ehcc_session")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

for r in (auth, dashboard, transactions, players, settings):
    app.include_router(r.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Content-Security-Policy",
                            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
                            "frame-ancestors 'none'; form-action 'self'")
    if request.url.path not in ("/healthz", "/favicon.ico") and not request.url.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(Path(__file__).parent / "static" / "favicon.ico", media_type="image/x-icon")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return PlainTextResponse("ok")


@app.exception_handler(LoginRequired)
async def login_required(request: Request, exc: LoginRequired):
    return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)


def _error(request: Request, code: int, message: str):
    with SessionLocal() as db:
        return page(request, db, "error.html", teambar=False, status_code=code, code=code, message=message)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return _error(request, exc.status_code, str(exc.detail))


@app.exception_handler(LedgerError)
async def ledger_error(request: Request, exc: LedgerError):
    return _error(request, 400, str(exc))
