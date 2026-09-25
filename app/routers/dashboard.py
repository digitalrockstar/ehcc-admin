from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import ledger
from ..services.views import describe, load_transactions_query
from .. import models as m
from ..web import page, resolve_team

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    team = resolve_team(request, db)
    if team is None:
        return page(request, db, "dashboard.html", team=None, summary=None)
    summary = ledger.team_summary(db, team.id)
    pending = ledger.team_pending_totals(ledger.pending_positions(db, team.id))
    balances = [r for r in ledger.player_balances(db, team.id) if r["net"] > 0][:5]
    recent = db.scalars(load_transactions_query().where(m.Transaction.team_id == team.id,
                                                        m.Transaction.status == "active")
                        .order_by(m.Transaction.transaction_date.desc(), m.Transaction.id.desc()).limit(10)).unique().all()
    return page(request, db, "dashboard.html", team=team, summary=summary, pending=pending, top=balances,
                recent=describe(db, list(recent)), account=ledger.get_team_account(db, team.id))
