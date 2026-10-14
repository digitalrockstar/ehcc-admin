from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..security import (admin_form, check_password, clear_failures, csrf_token, record_failure,
                        throttled)
from ..web import flash, page, safe_next

router = APIRouter()


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/login")
def login_form(request: Request, next: str = "/", db: Session = Depends(get_db)):
    return page(request, db, "login.html", teambar=False, next=safe_next(next, "/"),
                configured=bool(config.ADMIN_PASSWORD))


@router.post("/login")
def login(request: Request, name: str = Form(""), password: str = Form(""), next: str = Form("/"),
          db: Session = Depends(get_db)):
    ip = _ip(request)
    name = " ".join(name.split())[:40]

    def fail(msg: str, code: int):
        flash(request, msg, "err")
        return page(request, db, "login.html", teambar=False, next=safe_next(next, "/"),
                    configured=bool(config.ADMIN_PASSWORD), status_code=code)

    if not config.ADMIN_PASSWORD:
        return fail("Admin login is not configured. Set ADMIN_PASSWORD on the server.", 503)
    if throttled(ip):
        return fail("Too many failed attempts. Wait a few minutes and try again.", 429)
    if not name:
        return fail("Enter your name so changes can be attributed to you in the audit log.", 400)
    if not check_password(password):
        record_failure(ip)
        return fail("Wrong password.", 401)
    clear_failures(ip)
    import time
    request.session.update({"admin": True, "admin_name": name, "admin_at": time.time()})
    request.session.pop("csrf", None)
    csrf_token(request)
    return RedirectResponse(safe_next(next, "/"), status_code=303)


@router.post("/logout")
def logout(request: Request, form=Depends(admin_form)):
    for k in ("admin", "admin_name", "admin_at", "csrf"):
        request.session.pop(k, None)
    return RedirectResponse("/", status_code=303)
