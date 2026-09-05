from sqlalchemy.orm import Session
from .. import models


def get_player_balance(db: Session, player_id: int) -> dict:
    owed_by = sum(
        float(f.fee_amount) for f in db.query(models.MatchParticipant).filter(
            models.MatchParticipant.player_id == player_id,
            models.MatchParticipant.status == models.PaymentStatus.due,
        ).all()
    )
    owed_by += sum(
        float(a.amount) for a in db.query(models.ExpenseAllocation).filter(
            models.ExpenseAllocation.player_id == player_id,
            models.ExpenseAllocation.status == models.PaymentStatus.due,
        ).all()
    )
    owed_to = sum(
        float(e.amount) for e in db.query(models.TeamExpense).filter(
            models.TeamExpense.paid_by_player_id == player_id,
            models.TeamExpense.reimbursement_status == models.ReimbursementStatus.due,
        ).all()
    )
    return {"owed_by": owed_by, "owed_to": owed_to, "net": owed_to - owed_by}


def list_players_with_balances(db: Session, team_id: int) -> list:
    players = db.query(models.Player).filter(models.Player.team_id == team_id).order_by(models.Player.name).all()
    rows = []
    for p in players:
        balance = get_player_balance(db, p.id)
        rows.append({"player": p, **balance})
    return rows
