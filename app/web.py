"""Shared helpers for routes: templating, team context, flash messages, safe redirects."""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, models as m
from .formatting import dmy, inr, ist, mask_mobile
from .security import admin_name, csrf_token, is_admin
from .services.ledger import get_setting
from .services.views import item_label
from .themes import DEFAULT_THEME, css_block, valid_theme

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.filters.update({"inr": inr, "dmy": dmy, "ist": ist})
templates.env.globals["item_label"] = item_label


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session.setdefault("_flash", []).append([kind, message])


def safe_next(target: str | None, default: str) -> str:
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def redirect(request: Request, form, default: str) -> RedirectResponse:
    return RedirectResponse(safe_next(form.get("next"), default), status_code=303)


def all_teams(db: Session) -> list[m.Team]:
    return list(db.scalars(select(m.Team).order_by(m.Team.status, func.lower(m.Team.name))).all())


def resolve_team(request: Request, db: Session, force: m.Team | None = None) -> m.Team | None:
    teams = all_teams(db)
    if force is not None:
        team = force
    else:
        wanted = request.query_params.get("team") or request.session.get("team_id")
        team = next((t for t in teams if str(t.id) == str(wanted)), None)
        if team is None:
            team = next((t for t in teams if t.status == "active"), None) or (teams[0] if teams else None)
    if team is not None:
        request.session["team_id"] = team.id
    return team


def page(request: Request, db: Session, name: str, *, status_code: int = 200, teambar: bool = True,
         team: m.Team | None = None, teambar_path: str | None = None, **ctx):
    theme = get_setting(db, "theme", DEFAULT_THEME)
    ctx.update(
        request=request, is_admin=is_admin(request), admin_name=admin_name(request),
        csrf=csrf_token(request), theme_css=css_block(theme if valid_theme(theme) else DEFAULT_THEME),
        teams=all_teams(db) if teambar else [], team=team, show_teambar=teambar,
        teambar_path=teambar_path or request.url.path,
        flashes=request.session.pop("_flash", []), path=request.url.path,
        show_mobile=is_admin(request) or config.SHOW_MOBILE_TO_VIEWERS, mask_mobile=mask_mobile,
    )
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
