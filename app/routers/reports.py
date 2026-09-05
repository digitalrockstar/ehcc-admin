from fastapi import APIRouter, Depends, Request
from ..auth import require_admin
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.match_service import get_match_financials

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/reports")
def reports(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)

    players = db.query(models.Player).filter(models.Player.team_id == team.id).all()
    player_rows = []
    for p in players:
        owed_by = sum(
            float(f.fee_amount) for f in db.query(models.MatchParticipant).filter(
                models.MatchParticipant.player_id == p.id, models.MatchParticipant.status == models.PaymentStatus.due
            ).all()
        )
        owed_by += sum(
            float(a.amount) for a in db.query(models.ExpenseAllocation).filter(
                models.ExpenseAllocation.player_id == p.id, models.ExpenseAllocation.status == models.PaymentStatus.due
            ).all()
        )
        owed_to = sum(
            float(e.amount) for e in db.query(models.TeamExpense).filter(
                models.TeamExpense.paid_by_player_id == p.id,
                models.TeamExpense.reimbursement_status == models.ReimbursementStatus.due,
            ).all()
        )
        player_rows.append({"player": p, "owed_by": owed_by, "owed_to": owed_to, "net": owed_to - owed_by})

    matches = db.query(models.Match).filter(models.Match.team_id == team.id).all()
    match_rows = [{"match": m, **get_match_financials(db, m.id)} for m in matches]

    return templates.TemplateResponse("reports.html", {
        "request": request, "team": team, "player_rows": player_rows, "match_rows": match_rows,
    })
