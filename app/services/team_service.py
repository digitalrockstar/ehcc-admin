from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models
from .calculations import calculate_match_surplus, calculate_outstanding_fees


def get_account_balance(db: Session, team_id: int) -> float:
    """Cash actually available today - excludes transactions dated in the future."""
    team = db.query(models.Team).get(team_id)
    total = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
        models.Transaction.team_id == team_id, models.Transaction.date <= date.today(),
    ).scalar()
    return float(team.starting_balance) + float(total)


def get_future_balance(db: Session, team_id: int) -> float:
    """Projected balance once every recorded transaction (including
    future-dated ones) has actually landed."""
    team = db.query(models.Team).get(team_id)
    total = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
        models.Transaction.team_id == team_id
    ).scalar()
    return float(team.starting_balance) + float(total)


def get_dashboard_summary(db: Session, team_id: int) -> dict:
    account = get_account_balance(db, team_id)

    collections = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
        models.Transaction.team_id == team_id,
        models.Transaction.type.in_([
            models.TransactionType.match_fee_paid,
            models.TransactionType.player_receivable_paid,
        ]),
    ).scalar()

    cash_expenses = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
        models.Transaction.team_id == team_id,
        models.Transaction.type.in_([
            models.TransactionType.match_expense_account,
            models.TransactionType.team_expense_account,
            models.TransactionType.reimbursement,
        ]),
    ).scalar()

    adhoc_income = db.query(func.coalesce(func.sum(models.AdHocIncome.amount), 0)).filter(
        models.AdHocIncome.team_id == team_id
    ).scalar()

    # Match surplus across all non-cancelled matches
    match_surplus_total = 0
    matches = db.query(models.Match).filter(
        models.Match.team_id == team_id, models.Match.status != models.MatchStatus.cancelled
    ).all()
    players_owe_from_matches = 0
    for m in matches:
        obligations = sum(float(p.fee_amount) for p in m.participants)
        collected = sum(float(p.amount_paid) for p in m.participants if p.status == models.PaymentStatus.paid)
        match_surplus_total += calculate_match_surplus(collected, obligations)
        players_owe_from_matches += calculate_outstanding_fees(collected, obligations)

    # Outstanding expense allocations (players owe team)
    players_owe_from_expenses = db.query(
        func.coalesce(func.sum(models.ExpenseAllocation.amount), 0)
    ).filter(
        models.ExpenseAllocation.status == models.PaymentStatus.due,
        models.ExpenseAllocation.expense_id.in_(
            db.query(models.TeamExpense.id).filter(models.TeamExpense.team_id == team_id)
        ),
    ).scalar()

    # Team owes players (unreimbursed personally-paid expenses)
    team_owes_players = db.query(
        func.coalesce(func.sum(models.TeamExpense.amount), 0)
    ).filter(
        models.TeamExpense.team_id == team_id,
        models.TeamExpense.payment_source == models.PaymentSource.player,
        models.TeamExpense.reimbursement_status == models.ReimbursementStatus.due,
    ).scalar()

    return {
        "starting_balance": float(db.query(models.Team).get(team_id).starting_balance),
        "account": account,
        "future_balance": get_future_balance(db, team_id),
        "cash_collections": float(collections),
        "cash_expenses": abs(float(cash_expenses)),
        "additional_income": float(adhoc_income) + match_surplus_total,
        "players_owe_team": float(players_owe_from_matches) + float(players_owe_from_expenses),
        "team_owes_players": float(team_owes_players),
    }


def reset_all_data(db: Session) -> None:
    """Wipe every row in every table. Used for post-testing resets before
    a real season starts. Deleted in FK-safe order; nothing is soft-deleted
    here on purpose - this is meant to be a genuine clean slate."""
    for model in [
        models.Transaction, models.Reimbursement, models.ExpenseAllocation,
        models.TeamExpense, models.AdHocIncome, models.MatchParticipant,
        models.Match, models.Player, models.ExpenseCategory, models.IncomeType,
        models.Team,
    ]:
        db.query(model).delete()
    db.commit()
