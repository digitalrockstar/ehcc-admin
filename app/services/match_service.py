from datetime import date
from sqlalchemy.orm import Session
from .. import models
from .calculations import (
    calculate_match_player_fee,
    calculate_match_surplus,
    calculate_fees_settled,
    calculate_outstanding_fees,
)


def create_match(db: Session, team_id: int, match_date: date, ground_fees: float,
                  additional_amount: float, player_ids: list, notes: str = None) -> models.Match:
    total_expense = ground_fees + additional_amount
    fee = calculate_match_player_fee(int(round(total_expense)), len(player_ids))

    match = models.Match(
        team_id=team_id, match_date=match_date, status=models.MatchStatus.upcoming,
        notes=notes, ground_fees=ground_fees, additional_amount=additional_amount,
    )
    db.add(match)
    db.flush()

    for pid in player_ids:
        db.add(models.MatchParticipant(match_id=match.id, player_id=pid, fee_amount=fee))

    db.commit()
    db.refresh(match)
    return match


def pay_match_expense_from_account(db: Session, match_id: int) -> models.Match:
    match = db.query(models.Match).get(match_id)
    if match.expense_paid_from_account:
        return match
    db.add(models.Transaction(
        team_id=match.team_id, date=date.today(), type=models.TransactionType.match_expense_account,
        amount=-float(match.total_expense), match_id=match.id,
        description=f"Match expense - {match.match_date}",
    ))
    match.expense_paid_from_account = True
    match.status = models.MatchStatus.completed
    db.commit()
    db.refresh(match)
    return match


def mark_match_fee_paid(db: Session, participant_id: int, amount_paid: float = None,
                         payment_date: date = None) -> models.MatchParticipant:
    p = db.query(models.MatchParticipant).get(participant_id)
    amount = amount_paid if amount_paid is not None else float(p.fee_amount)
    p.amount_paid = amount
    p.status = models.PaymentStatus.paid
    p.payment_date = payment_date or date.today()
    db.add(models.Transaction(
        team_id=p.match.team_id, date=p.payment_date, type=models.TransactionType.match_fee_paid,
        amount=amount, party_player_id=p.player_id, match_id=p.match_id,
        description=f"Match fee - {p.player.name}",
    ))
    db.commit()
    db.refresh(p)
    return p


def get_match_financials(db: Session, match_id: int) -> dict:
    match = db.query(models.Match).get(match_id)
    obligations = sum(float(p.fee_amount) for p in match.participants)
    collected = sum(float(p.amount_paid) for p in match.participants if p.status == models.PaymentStatus.paid)
    return {
        "total_expense": float(match.total_expense),
        "player_fee": float(match.participants[0].fee_amount) if match.participants else 0,
        "total_fee_obligations": obligations,
        "total_collected": collected,
        "fees_settled": calculate_fees_settled(collected, obligations),
        "outstanding": calculate_outstanding_fees(collected, obligations),
        "match_surplus": calculate_match_surplus(collected, obligations),
    }


def cancel_match(db: Session, match_id: int) -> models.Match:
    match = db.query(models.Match).get(match_id)
    match.status = models.MatchStatus.cancelled
    db.commit()
    db.refresh(match)
    return match
