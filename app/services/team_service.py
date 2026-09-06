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


def reset_data_before(db: Session, team_id: int, cutoff_utc) -> None:
    """Delete matches/expenses/income (and their transactions/allocations/
    reimbursements) created before cutoff_utc, keeping anything created at
    or after it. The Team row itself and players still referenced by kept
    records are left alone - this is a partial cleanup, not a full wipe."""
    old_match_ids = [m.id for m in db.query(models.Match).filter(
        models.Match.team_id == team_id, models.Match.created_at < cutoff_utc)]
    old_expense_ids = [e.id for e in db.query(models.TeamExpense).filter(
        models.TeamExpense.team_id == team_id, models.TeamExpense.created_at < cutoff_utc)]
    old_income_ids = [i.id for i in db.query(models.AdHocIncome).filter(
        models.AdHocIncome.team_id == team_id, models.AdHocIncome.created_at < cutoff_utc)]

    if old_match_ids:
        db.query(models.Transaction).filter(models.Transaction.match_id.in_(old_match_ids)).delete(synchronize_session=False)
        db.query(models.MatchParticipant).filter(models.MatchParticipant.match_id.in_(old_match_ids)).delete(synchronize_session=False)
        db.query(models.Match).filter(models.Match.id.in_(old_match_ids)).delete(synchronize_session=False)
    if old_expense_ids:
        db.query(models.Transaction).filter(models.Transaction.expense_id.in_(old_expense_ids)).delete(synchronize_session=False)
        db.query(models.ExpenseAllocation).filter(models.ExpenseAllocation.expense_id.in_(old_expense_ids)).delete(synchronize_session=False)
        db.query(models.Reimbursement).filter(models.Reimbursement.expense_id.in_(old_expense_ids)).delete(synchronize_session=False)
        db.query(models.TeamExpense).filter(models.TeamExpense.id.in_(old_expense_ids)).delete(synchronize_session=False)
    if old_income_ids:
        db.query(models.Transaction).filter(models.Transaction.income_id.in_(old_income_ids)).delete(synchronize_session=False)
        db.query(models.AdHocIncome).filter(models.AdHocIncome.id.in_(old_income_ids)).delete(synchronize_session=False)
    db.commit()

    # Players created before cutoff with nothing left referencing them
    for p in db.query(models.Player).filter(models.Player.team_id == team_id, models.Player.created_at < cutoff_utc).all():
        referenced = (
            db.query(models.MatchParticipant).filter(models.MatchParticipant.player_id == p.id).first()
            or db.query(models.ExpenseAllocation).filter(models.ExpenseAllocation.player_id == p.id).first()
            or db.query(models.TeamExpense).filter(models.TeamExpense.paid_by_player_id == p.id).first()
            or db.query(models.Reimbursement).filter(models.Reimbursement.player_id == p.id).first()
        )
        if not referenced:
            db.delete(p)
    db.commit()
