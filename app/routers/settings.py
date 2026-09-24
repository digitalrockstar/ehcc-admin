import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, models as m
from ..db import get_db
from ..security import admin_form, admin_name, require_admin_page
from ..services import ledger, masters
from ..services.audit import log
from ..services.ledger import LedgerError
from ..themes import DEFAULT_THEME, theme_list, valid_theme
from ..web import all_teams, flash, page, redirect

router = APIRouter()


@router.get("/settings")
def settings(request: Request, db: Session = Depends(get_db), _=Depends(require_admin_page)):
    teams = all_teams(db)
    rows = []
    for t in teams:
        acct = ledger.get_team_account(db, t.id)
        rows.append({"team": t, "account": acct, "opening": ledger.opening_balance(db, t.id),
                     "players": db.scalar(select(func.count()).select_from(m.Player).where(m.Player.team_id == t.id))})
    cats = db.scalars(select(m.Category).order_by(m.Category.kind, m.Category.sort_order)).all()
    return page(request, db, "settings.html", teambar=False, rows=rows,
                categories=cats, themes=theme_list(), current_theme=ledger.get_setting(db, "theme", DEFAULT_THEME),
                step=int(ledger.rounding_step(db)))


def _run(request, form, db, action, msg, anchor=""):
    try:
        result = action()
        db.commit()
        flash(request, msg(result) if callable(msg) else msg)
    except LedgerError as e:
        db.rollback()
        flash(request, str(e), "err")
    return redirect(request, {"next": "/settings" + anchor}, "/settings")


def _int_id(v) -> int:
    return int(v)


@router.post("/settings/teams/add")
def team_add(request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    def go():
        opening = masters.parse_amount(form.get("opening"), allow_negative=True) if form.get("opening") else None
        masters.create_team(db, form.get("name"), admin_name(request), opening)
    return _run(request, form, db, go, "Team and team account created.", "#teams")


@router.post("/settings/teams/{team_id}/edit")
def team_edit(team_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _run(request, form, db, lambda: masters.rename_team(db, team_id, form.get("name"), admin_name(request)),
                "Team renamed.", "#teams")


@router.post("/settings/teams/{team_id}/archive")
def team_archive(team_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    archived = form.get("archive") == "1"
    return _run(request, form, db, lambda: masters.set_team_archived(db, team_id, archived, admin_name(request)),
                "Team archived." if archived else "Team restored.", "#teams")


@router.post("/settings/teams/{team_id}/opening-balance")
def team_opening(team_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _run(request, form, db, lambda: masters.set_opening_balance(
        db, team_id, masters.parse_amount(form.get("amount"), allow_negative=True), admin_name(request)),
        "Starting balance saved.", "#teams")


@router.post("/settings/categories/add")
def cat_add(request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _run(request, form, db, lambda: masters.create_category(
        db, form.get("name"), form.get("kind"), admin_name(request)), "Category added.", "#categories")


@router.post("/settings/categories/{cat_id}/edit")
def cat_edit(cat_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _run(request, form, db, lambda: masters.rename_category(db, cat_id, form.get("name"), admin_name(request)),
                "Category renamed.", "#categories")


@router.post("/settings/categories/{cat_id}/archive")
def cat_archive(cat_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    archived = form.get("archive") == "1"
    return _run(request, form, db, lambda: masters.set_category_archived(db, cat_id, archived, admin_name(request)),
                "Category archived." if archived else "Category restored.", "#categories")


@router.post("/settings/theme")
def theme(request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    slug = str(form.get("theme", ""))

    def go():
        if not valid_theme(slug):
            raise LedgerError("Unknown theme.")
        ledger.set_setting(db, "theme", slug)
        log(db, admin_name(request), "settings.theme", "settings", None, None, {"theme": slug})
    return _run(request, form, db, go, "Theme applied.", "#themes")


@router.post("/settings/rounding")
def rounding(request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    def go():
        raw = str(form.get("step", "")).strip()
        if not raw.isdigit() or not (1 <= int(raw) <= 100):
            raise LedgerError("Rounding step must be a whole number from 1 to 100.")
        old = ledger.rounding_step(db)
        ledger.set_setting(db, "rounding_step", raw)
        log(db, admin_name(request), "settings.rounding", "settings", None, None, {"from": old, "to": raw})
    return _run(request, form, db, go, "Rounding step saved. It applies to new and edited transactions.", "#rounding")


@router.post("/settings/reset")
def reset(request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    def go():
        if str(form.get("confirm", "")).strip() != "DELETE":
            raise LedgerError("Type DELETE to confirm the reset.")
        since = None
        if form.get("scope") == "since":
            try:
                local = dt.datetime.fromisoformat(str(form.get("since", "")))
            except ValueError:
                raise LedgerError("Choose the date and time to delete from.")
            since = local.replace(tzinfo=ZoneInfo(config.TIMEZONE)).astimezone(dt.timezone.utc)
        return ledger.reset_data(db, admin_name(request), since=since)
    return _run(request, form, db, go,
                lambda r: f"Deleted {r['transactions']} transactions. The audit log was kept.", "#reset")


@router.get("/audit")
def audit(request: Request, p: int = 1, db: Session = Depends(get_db), _=Depends(require_admin_page)):
    size = 100
    total = db.scalar(select(func.count()).select_from(m.AuditLog))
    rows = db.scalars(select(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(size).offset((max(p, 1) - 1) * size)).all()
    return page(request, db, "audit.html", teambar=False, rows=rows, p=max(p, 1), pages=max(1, -(-total // size)))
