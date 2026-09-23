from decimal import Decimal
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..deps import templates, get_selected_team, all_teams
from .. import models
from ..services import ledger_service as ledger

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    team = get_selected_team(request, db)
    if not team:
        return templates.TemplateResponse("setup.html", {"request": request, "teams": all_teams(db)})

    total_in = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter_by(
        team_id=team.id, type="income", status="active").scalar() or 0
    total_out = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter_by(
        team_id=team.id, type="expense", status="active").scalar() or 0
    surplus = db.query(func.coalesce(func.sum(models.Transaction.surplus_amount), 0)).filter_by(
        team_id=team.id, type="expense", status="active").scalar() or 0

    cat_rows = (
        db.query(models.Category.name, func.sum(models.Transaction.amount))
        .join(models.Transaction, models.Transaction.category_id == models.Category.id)
        .filter(models.Transaction.team_id == team.id, models.Transaction.type == "expense",
                models.Transaction.status == "active")
        .group_by(models.Category.name)
        .having(func.sum(models.Transaction.amount) > 0)
        .all()
    )

    players = db.query(models.Player).filter_by(team_id=team.id, is_archived=False).all()
    outstanding = sorted(
        ({"player": p, **ledger.player_totals(db, p)} for p in players),
        key=lambda r: r["net_outstanding"], reverse=True,
    )[:5]

    recent = (
        db.query(models.Transaction)
        .filter_by(team_id=team.id, status="active")
        .order_by(models.Transaction.transaction_date.desc(), models.Transaction.id.desc())
        .limit(10).all()
    )

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "team": team, "teams": all_teams(db),
        "balance": ledger.team_balance(db, team),
        "total_in": Decimal(total_in), "total_out": Decimal(total_out), "surplus": Decimal(surplus),
        "cat_rows": cat_rows, "outstanding": outstanding, "recent": recent,
    })
