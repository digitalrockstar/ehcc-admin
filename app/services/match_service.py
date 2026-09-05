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


class ConfirmationRequired(Exception):
    """Raised when an edit/cancel touches existing payments and the caller
    has not yet passed confirm=True. The route layer catches this and
    re-renders the page with a warning instead of a hard 400."""
    def __init__(self, message: str, preview: dict = None):
        super().__init__(message)
        self.preview = preview or {}


class InvalidEdit(Exception):
    """A hard stop, not a confirmable warning - e.g. trying to remove a
    player who has already paid their fee. There's no cash-safe way to
    silently apply this, so it's rejected outright."""
    pass


def preview_match_edit(db: Session, match_id: int, new_ground_fees: float, new_additional_amount: float,
                        new_player_ids: list) -> dict:
    """Section 38: show the financial impact of an edit before saving.
    Covers both the amount changing and players being added/removed."""
    match = db.query(models.Match).get(match_id)
    current = {p.player_id: p for p in match.participants}
    new_ids = set(new_player_ids)
    current_ids = set(current.keys())

    to_remove = current_ids - new_ids
    to_add = new_ids - current_ids
    paid_being_removed = [current[pid] for pid in to_remove if current[pid].status == models.PaymentStatus.paid]

    old_total = float(match.total_expense)
    new_total = new_ground_fees + new_additional_amount
    old_fee = float(match.participants[0].fee_amount) if match.participants else 0
    new_fee = calculate_match_player_fee(int(round(new_total)), len(new_ids)) if new_ids else 0
    paid_count = sum(1 for p in match.participants if p.status == models.PaymentStatus.paid)

    return {
        "old_total_expense": old_total, "new_total_expense": new_total,
        "old_fee": old_fee, "new_fee": new_fee,
        "paid_count": paid_count, "total_players": len(match.participants),
        "new_total_players": len(new_ids),
        "to_add": list(to_add), "to_remove": list(to_remove),
        "paid_being_removed": [p.player.name for p in paid_being_removed],
        "has_payments": paid_count > 0 or match.expense_paid_from_account,
    }


def apply_match_edit(db: Session, match_id: int, new_ground_fees: float, new_additional_amount: float,
                      new_player_ids: list, confirmed: bool = False) -> models.Match:
    match = db.query(models.Match).get(match_id)
    preview = preview_match_edit(db, match_id, new_ground_fees, new_additional_amount, new_player_ids)

    if preview["paid_being_removed"]:
        raise InvalidEdit(
            "Can't remove " + ", ".join(preview["paid_being_removed"]) +
            " - they've already paid their match fee. Keep them selected, or handle "
            "this manually before removing them."
        )

    if preview["has_payments"] and not confirmed:
        raise ConfirmationRequired(
            "This match has existing payments. Confirm to apply the recalculated fee "
            "to unpaid players and any newly added players; already-paid fees are left untouched.",
            preview=preview,
        )

    match.ground_fees = new_ground_fees
    match.additional_amount = new_additional_amount
    new_fee = preview["new_fee"]

    for pid in preview["to_remove"]:
        participant = next(p for p in match.participants if p.player_id == pid)
        db.delete(participant)

    for pid in preview["to_add"]:
        db.add(models.MatchParticipant(match_id=match.id, player_id=pid, fee_amount=new_fee))

    db.flush()
    # Never overwrite an already-paid fee. Every unpaid obligation (existing
    # or newly added) moves to the recalculated amount.
    for p in match.participants:
        if p.status == models.PaymentStatus.due:
            p.fee_amount = new_fee

    db.commit()
    db.refresh(match)
    return match


def cancel_match(db: Session, match_id: int, confirmed: bool = False) -> models.Match:
    match = db.query(models.Match).get(match_id)
    has_payments = any(p.status == models.PaymentStatus.paid for p in match.participants) or match.expense_paid_from_account

    if has_payments and not confirmed:
        raise ConfirmationRequired(
            "This match has recorded payments/expense. Cancelling removes it from active "
            "totals but keeps the full history visible. Confirm to proceed.",
        )

    match.status = models.MatchStatus.cancelled
    db.commit()
    db.refresh(match)
    return match
