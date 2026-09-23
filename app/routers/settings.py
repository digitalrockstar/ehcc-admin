from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from ..database import get_db
from ..auth import require_admin
from ..deps import templates, all_teams
from .. import models
from ..services.ledger_service import log

router = APIRouter()


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    teams = db.query(models.Team).order_by(models.Team.name).all()
    income_cats = db.query(models.Category).filter_by(type="income").all()
    expense_cats = db.query(models.Category).filter_by(type="expense").all()
    from ..routers.theme import VALID_THEMES
    return templates.TemplateResponse("settings.html", {
        "request": request, "teams": teams, "team": None,
        "income_cats": income_cats, "expense_cats": expense_cats,
        "themes": sorted(VALID_THEMES),
    })


@router.post("/settings/categories")
def add_category(type: str = Form(...), name: str = Form(...),
                  db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    name = name.strip()
    if name and not db.query(models.Category).filter_by(type=type, name=name).first():
        cat = models.Category(type=type, name=name)
        db.add(cat)
        db.flush()
        log(db, "admin", "create", "category", cat.id, f"{type}:{name}")
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/categories/{category_id}/archive")
def archive_category(category_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    cat = db.query(models.Category).get(category_id)
    if cat:
        cat.is_archived = True
        log(db, "admin", "archive", "category", cat.id)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/reset")
def reset_data(cutoff: str = Form(""), db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    """Delete all data, or all data created after a given datetime (IST-naive,
    matches created_at which is stored in UTC-naive form)."""
    q_txn = db.query(models.Transaction)
    q_alloc = db.query(models.Allocation)
    if cutoff:
        cutoff_dt = datetime.fromisoformat(cutoff)
        q_txn = q_txn.filter(models.Transaction.created_at >= cutoff_dt)
        ids = [t.id for t in q_txn.all()]
        q_alloc = q_alloc.filter(models.Allocation.transaction_id.in_(ids))
    q_alloc.delete(synchronize_session=False)
    q_txn.delete(synchronize_session=False)
    log(db, "admin", "reset", "transaction", None, f"cutoff={cutoff or 'ALL'}")
    db.commit()
    return RedirectResponse("/settings", status_code=303)
