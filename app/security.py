import hmac
import secrets
import time

from fastapi import HTTPException, Request

from . import config


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def is_admin(request: Request) -> bool:
    s = request.session
    if not s.get("admin"):
        return False
    if time.time() - s.get("admin_at", 0) > config.ADMIN_SESSION_HOURS * 3600:
        s.pop("admin", None)
        return False
    return True


def admin_name(request: Request) -> str:
    return request.session.get("admin_name") or "admin"


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        request.session["csrf"] = tok
    return tok


def require_admin_page(request: Request) -> None:
    if not is_admin(request):
        raise LoginRequired(request.url.path)


async def admin_form(request: Request):
    """Dependency for every mutating route: admin session + CSRF token, returns the parsed form."""
    if not is_admin(request):
        raise HTTPException(403, "Admin login required.")
    form = await request.form()
    sent = str(form.get("csrf_token", ""))
    if not sent or not hmac.compare_digest(sent, request.session.get("csrf", "")):
        raise HTTPException(403, "Security token missing or expired. Reload the page and try again.")
    return form


def check_password(candidate: str) -> bool:
    if not config.ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(candidate.encode(), config.ADMIN_PASSWORD.encode())


_fails: dict[str, list[float]] = {}


def throttled(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 300]
    _fails[ip] = recent
    return len(recent) >= 5


def record_failure(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.time())


def clear_failures(ip: str) -> None:
    _fails.pop(ip, None)
