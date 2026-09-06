from datetime import date, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models

RECENT_DAYS = 30


def get_last_played_map(db: Session, team_id: int) -> dict:
    rows = db.query(
        models.MatchParticipant.player_id, func.max(models.Match.match_date)
    ).join(models.Match, models.Match.id == models.MatchParticipant.match_id).filter(
        models.Match.team_id == team_id, models.Match.status != models.MatchStatus.cancelled
    ).group_by(models.MatchParticipant.player_id).all()
    return dict(rows)


def sort_players_by_recency(players: list, last_played: dict) -> list:
    """Players with a match in the last 30 days come first, most recent
    first; everyone else follows alphabetically."""
    cutoff = date.today() - timedelta(days=RECENT_DAYS)

    def sort_key(p):
        lp = last_played.get(p.id)
        if lp and lp >= cutoff:
            return (0, -lp.toordinal())
        return (1, p.name.lower())

    return sorted(players, key=sort_key)


def get_players_sorted(db: Session, team_id: int, active_only: bool = False) -> list:
    query = db.query(models.Player).filter(models.Player.team_id == team_id)
    if active_only:
        query = query.filter(models.Player.status == models.PlayerStatus.active)
    players = query.all()
    return sort_players_by_recency(players, get_last_played_map(db, team_id))


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
    players = get_players_sorted(db, team_id)
    rows = []
    for p in players:
        balance = get_player_balance(db, p.id)
        rows.append({"player": p, **balance})
    return rows
