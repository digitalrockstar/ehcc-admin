"""All financial rules live here: allocations, team balance, credits, settlements and reversals."""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from ..config import DEFAULT_ROUNDING_STEP, TIMEZONE
from .audit import log

ZERO = Decimal("0.00")
TWO = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999.99")
NOSYNC = {"synchronize_session": False}


class LedgerError(Exception):
    """Base for all ledger rule violations. Message is safe to show the admin."""
    status_code = 400
    field = None

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


class NotFoundError(LedgerError):
    """The requested entity does not exist."""
    status_code = 404


class ConflictError(LedgerError):
    """The action conflicts with the current state (duplicate, already done, etc.)."""
    status_code = 409


def q2(v) -> Decimal:
    return Decimal(str(v if v is not None else 0)).quantize(TWO)


def today_ist() -> dt.date:
    return dt.datetime.now(ZoneInfo(TIMEZONE)).date()


# ---------------------------------------------------------------- settings

def get_setting(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(m.AppSetting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(m.AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(m.AppSetting(key=key, value=value))


def rounding_step(db: Session) -> Decimal:
    try:
        step = Decimal(get_setting(db, "rounding_step", str(DEFAULT_ROUNDING_STEP)))
    except InvalidOperation:
        step = Decimal(DEFAULT_ROUNDING_STEP)
    return step if step >= 1 else Decimal(DEFAULT_ROUNDING_STEP)


# ---------------------------------------------------------------- allocation

def per_party_charge(amount: Decimal, parties: int, step: Decimal) -> Decimal:
    """CEILING((amount / parties) / step) * step. A single party is charged the exact amount."""
    amount = Decimal(amount)
    if parties <= 1:
        return q2(amount)
    steps = (amount / (Decimal(parties) * Decimal(step))).to_integral_value(rounding=ROUND_CEILING)
    return q2(steps * Decimal(step))


# ---------------------------------------------------------------- lookups

def get_team_account(db: Session, team_id: int) -> m.Account:
    acct = db.scalar(select(m.Account).where(m.Account.team_id == team_id, m.Account.kind == "team"))
    if acct is None:
        raise NotFoundError("This team has no team account.")
    return acct


def _lock_txn(db: Session, txn_id: int) -> m.Transaction:
    t = db.scalar(select(m.Transaction).where(m.Transaction.id == txn_id)
                  .with_for_update().execution_options(populate_existing=True))
    if t is None:
        raise NotFoundError("Transaction not found.")
    return t


def _accounts_for_team(db: Session, team_id: int, ids: list[int]) -> list[m.Account]:
    if not ids:
        return []
    rows = db.scalars(select(m.Account).options(selectinload(m.Account.player), selectinload(m.Account.team))
                      .where(m.Account.id.in_(ids))).all()
    found = {a.id: a for a in rows}
    out = []
    for i in ids:
        a = found.get(i)
        if a is None or a.team_id != team_id:
            raise LedgerError("A selected account does not belong to this team.")
        if a.status != "active" or (a.player is not None and a.player.status != "active"):
            raise ConflictError(f"{a.name} is archived and cannot be used.")
        out.append(a)
    return out


# ---------------------------------------------------------------- create / edit

@dataclass
class TxnInput:
    team_id: int
    date: dt.date
    type: str
    amount: Decimal
    category_id: int | None = None
    item_description: str | None = None
    paid_by: int | None = None
    charged_to: list[int] = field(default_factory=list)
    account_in: int | None = None
    account_out: int | None = None


def _prepare(db: Session, d: TxnInput, keep_category_id: int | None = None) -> dict:
    team = db.get(m.Team, d.team_id)
    if team is None:
        raise LedgerError("Choose a team.", field="team_id")
    if team.status != "active":
        raise ConflictError("This team is archived. Restore it in Settings to add transactions.")
    if d.type not in m.TXN_TYPES:
        raise LedgerError("Choose a transaction type.", field="type")
    if not isinstance(d.date, dt.date):
        raise LedgerError("Choose a date.", field="transaction_date")
    amount = Decimal(d.amount)
    if amount != amount.quantize(TWO):
        raise LedgerError("Amount can have at most 2 decimal places.", field="amount")
    amount = q2(amount)
    if amount <= 0 or amount > MAX_AMOUNT:
        raise LedgerError("Amount must be a positive value below ₹1,00,00,000.", field="amount")
    desc = (d.item_description or "").strip() or None
    if desc and len(desc) > 200:
        raise LedgerError("Description is too long (200 characters max).", field="item_description")

    plan = {"team": team, "amount": amount, "desc": desc, "category": None,
            "links": [], "allocs": [], "surplus": ZERO}

    if d.type in ("expense", "income"):
        cat = db.get(m.Category, d.category_id) if d.category_id else None
        if cat is None or cat.kind != d.type:
            raise LedgerError("Choose a category.", field="category_id")
        if cat.status != "active" and cat.id != keep_category_id:
            raise ConflictError(f"Category '{cat.name}' is archived.")
        if cat.is_other and not desc:
            raise LedgerError("Describe the item when the category is 'Other'.", field="item_description")
        plan["category"] = cat

    if d.type == "expense":
        if not d.paid_by:
            raise LedgerError("Choose who paid.", field="paid_by")
        (payer,) = _accounts_for_team(db, team.id, [d.paid_by])
        ids = list(dict.fromkeys(d.charged_to))
        if not ids:
            raise LedgerError("Select at least one party to charge.", field="charged_to")
        parties = _accounts_for_team(db, team.id, ids)
        share = per_party_charge(amount, len(parties), rounding_step(db))
        plan["links"] = [("paid_by", payer)]
        plan["allocs"] = [(a, share) for a in parties]
        plan["surplus"] = q2(share * len(parties) - amount) if len(parties) > 1 else ZERO
    elif d.type == "income":
        plan["links"] = [("account_in", get_team_account(db, team.id))]
        if d.paid_by:
            (payer,) = _accounts_for_team(db, team.id, [d.paid_by])
            if payer.kind != "player":
                raise LedgerError("Income can only be paid in by a player, or left as external.", field="paid_by_income")
            plan["links"].append(("paid_by", payer))
    else:
        if not d.account_in or not d.account_out:
            raise LedgerError("Choose both the account in and the account out.", field="account_in")
        if d.account_in == d.account_out:
            raise LedgerError("Account in and account out must be different.", field="account_in")
        acc_in, acc_out = _accounts_for_team(db, team.id, [d.account_in, d.account_out])
        plan["links"] = [("account_in", acc_in), ("account_out", acc_out)]
    return plan


def snapshot(t: m.Transaction) -> dict:
    return {
        "date": t.transaction_date, "type": t.type, "amount": t.amount, "status": t.status,
        "category": t.category.name if t.category else None, "description": t.item_description,
        "surplus": t.surplus_amount,
        "links": {ta.role: ta.account.name for ta in t.accounts},
        "charged_to": sorted(a.account.name for a in t.allocations),
        "allocated_each": sorted({str(a.allocated_amount) for a in t.allocations}),
    }


def create_transaction(db: Session, d: TxnInput, actor: str) -> m.Transaction:
    plan = _prepare(db, d)
    t = m.Transaction(team_id=plan["team"].id, transaction_date=d.date, type=d.type,
                      category_id=plan["category"].id if plan["category"] else None,
                      item_description=plan["desc"], amount=plan["amount"],
                      surplus_amount=plan["surplus"], status="active", created_by=actor)
    for role, acct in plan["links"]:
        t.accounts.append(m.TransactionAccount(account_id=acct.id, role=role))
    payer_id = d.paid_by if d.type == "expense" else None
    for acct, share in plan["allocs"]:
        # The payer's own selected share is already covered by the expense they fronted.
        t.allocations.append(m.Allocation(account_id=acct.id, allocated_amount=share,
                                          settlement_status=1 if acct.id == payer_id else 0))
    db.add(t)
    db.flush()
    db.refresh(t)
    log(db, actor, "transaction.create", "transaction", t.id, t.team_id, snapshot(t))
    return t


def has_active_settlements(db: Session, txn_id: int) -> bool:
    return db.scalar(select(func.count()).select_from(m.Settlement)
                     .where(m.Settlement.transaction_id == txn_id, m.Settlement.status == "active")) > 0


def settlement_for_transfer(db: Session, txn_id: int) -> m.Settlement | None:
    return db.scalar(select(m.Settlement).where(m.Settlement.settlement_transaction_id == txn_id,
                                                m.Settlement.status == "active"))


def update_transaction(db: Session, txn_id: int, d: TxnInput, actor: str) -> m.Transaction:
    """Edit an expense without erasing collection history; overpayments become player credits."""
    t = _lock_txn(db, txn_id)
    if t.status != "active":
        raise ConflictError("Only active transactions can be edited.")
    if settlement_for_transfer(db, t.id):
        raise ConflictError("This transfer was created by a settlement. Reverse the settlement instead.")
    active_settlements = db.scalars(select(m.Settlement).where(
        m.Settlement.transaction_id == t.id, m.Settlement.status == "active")).all()
    if any(s.kind == "reimbursement" for s in active_settlements):
        raise ConflictError("Reverse the reimbursement before editing this transaction.")
    if d.type != t.type or d.team_id != t.team_id:
        raise LedgerError("Type and team cannot be changed. Void this transaction and enter a new one.")
    before = snapshot(t)
    plan = _prepare(db, d, keep_category_id=t.category_id)
    if t.type != "expense" and active_settlements:
        raise ConflictError("Reverse active settlements before editing this transaction.")
    source_credit_ids = select(m.PlayerCredit.id).where(m.PlayerCredit.source_transaction_id == t.id)
    credit_in_use = db.scalar(select(func.count()).select_from(m.PlayerCreditMovement).where(
        m.PlayerCreditMovement.credit_id.in_(source_credit_ids),
        m.PlayerCreditMovement.kind.in_(("application", "team_transfer")),
        m.PlayerCreditMovement.reversed_at.is_(None)))
    if credit_in_use:
        raise ConflictError("Reverse this transaction's credit applications or team transfer before editing it.")

    # Capture historical collections before allocations are reconciled.
    old_allocs = {a.account_id: a for a in list(t.allocations)}
    collected = {}
    for aid, alloc in old_allocs.items():
        collected[aid] = q2(db.scalar(select(func.coalesce(func.sum(m.Settlement.amount), 0)).where(
            m.Settlement.allocation_id == alloc.id,
            m.Settlement.kind == "collection", m.Settlement.status == "active")))

    # Reverse only the automatic team-balance adjustment; original collection transfers remain
    # active and visible as real historical cash movements.
    for s in active_settlements:
        if s.kind == "team_balance":
            _reverse_row(db, s, actor, "Parent transaction edited")

    t.accounts.clear()
    db.flush()
    t.transaction_date = d.date
    t.category_id = plan["category"].id if plan["category"] else None
    t.item_description = plan["desc"]
    t.amount = plan["amount"]
    t.surplus_amount = plan["surplus"]
    for role, acct in plan["links"]:
        t.accounts.append(m.TransactionAccount(account_id=acct.id, role=role))

    new_allocs = {acct.id: (acct, share) for acct, share in plan["allocs"]}
    for aid, old in list(old_allocs.items()):
        if aid not in new_allocs:
            _reverse_credit_applications(db, old, actor)
            paid = collected.get(aid, ZERO)
            if paid > 0:
                _upsert_player_credit(db, t.team_id, aid, t.id, paid,
                                      f"Credit from removed allocation on transaction #{t.id}", actor)
            t.allocations.remove(old)
    db.flush()

    payer_id = plan["links"][0][1].id if t.type == "expense" and plan["links"] else None
    for aid, (acct, share) in new_allocs.items():
        old = old_allocs.get(aid)
        if old is None:
            old = m.Allocation(transaction_id=t.id, account_id=aid, allocated_amount=share)
            t.allocations.append(old)
        old.allocated_amount = share
        paid = collected.get(aid, ZERO)
        _reconcile_credit_applications(db, old, share, actor)
        applied_credit = _applied_credit(db, old)
        old.settlement_status = 1 if (aid == payer_id or paid + applied_credit >= share) else 0
        if old.settlement_status == 0:
            old.settled_transaction_id = None
        elif paid > 0:
            last = db.scalar(select(m.Settlement).where(
                m.Settlement.transaction_id == t.id, m.Settlement.account_id == aid,
                m.Settlement.kind == "collection", m.Settlement.status == "active")
                .order_by(m.Settlement.id.desc()))
            old.settled_transaction_id = last.settlement_transaction_id if last else None
        else:
            old.settled_transaction_id = None
        if paid > share:
            _upsert_player_credit(db, t.team_id, aid, t.id, paid - share,
                                  f"Overpayment from edited transaction #{t.id}", actor)
    db.flush()
    db.refresh(t)
    _finalize_team_balance_rounding(db, t, actor)
    log(db, actor, "transaction.edit", "transaction", t.id, t.team_id,
        {"before": before, "after": snapshot(t), "collections_preserved": True})
    return t

# ---------------------------------------------------------------- settlements

def _payer_account(t: m.Transaction) -> m.Account | None:
    for ta in t.accounts:
        if ta.role == "paid_by":
            return ta.account
    return None


def _make_transfer(db: Session, team_id: int, out_acct: m.Account, in_acct: m.Account,
                   amount: Decimal, note: str, actor: str) -> m.Transaction:
    tr = m.Transaction(team_id=team_id, transaction_date=today_ist(), type="transfer",
                       item_description=note, amount=amount, status="active", created_by=actor)
    tr.accounts.append(m.TransactionAccount(account_id=out_acct.id, role="account_out"))
    tr.accounts.append(m.TransactionAccount(account_id=in_acct.id, role="account_in"))
    db.add(tr)
    db.flush()
    return tr


def reimburse(db: Session, txn_id: int, actor: str) -> m.Settlement:
    t = _lock_txn(db, txn_id)
    if t.type != "expense" or t.status != "active":
        raise ConflictError("Only active expenses can be reimbursed.")
    payer = _payer_account(t)
    if payer is None or payer.kind != "player":
        raise ConflictError("Only expenses paid by a player can be reimbursed.")
    exists = db.scalar(select(m.Settlement.id).where(
        m.Settlement.transaction_id == t.id, m.Settlement.account_id == payer.id,
        m.Settlement.kind == "reimbursement", m.Settlement.status == "active"))
    if exists:
        raise ConflictError("This expense has already been reimbursed.")
    team_acct = get_team_account(db, t.team_id)
    try:
        with db.begin_nested():
            tr = _make_transfer(db, t.team_id, team_acct, payer, t.amount, f"Reimbursement for #{t.id}", actor)
            s = m.Settlement(kind="reimbursement", transaction_id=t.id, account_id=payer.id,
                             amount=t.amount, settlement_transaction_id=tr.id, status="active")
            db.add(s)
            db.flush()
    except IntegrityError:
        raise ConflictError("This expense has already been reimbursed.")
    log(db, actor, "settlement.reimburse", "transaction", t.id, t.team_id,
        {"to": payer.name, "amount": t.amount, "transfer_id": tr.id})
    return s


def collect(db: Session, allocation_id: int, actor: str) -> m.Settlement:
    a0 = db.get(m.Allocation, allocation_id)
    if a0 is None:
        raise NotFoundError("Allocation not found.")
    t = _lock_txn(db, a0.transaction_id)
    a = db.scalar(select(m.Allocation).where(m.Allocation.id == allocation_id)
                  .with_for_update().execution_options(populate_existing=True))
    if t.type != "expense" or t.status != "active":
        raise ConflictError("Collections apply to active expenses only.")
    if a.account.kind != "player":
        raise LedgerError("Only players are collected from. The team account is charged directly.")
    already_collected = _active_collected(db, a)
    already_credited = _applied_credit(db, a)
    amount_due = q2(max(ZERO, a.allocated_amount - already_collected - already_credited))
    if amount_due <= ZERO or a.settlement_status == 1:
        raise ConflictError(f"{a.account.name} has already paid this.")
    team_acct = get_team_account(db, t.team_id)
    payer = _payer_account(t)
    recipient = payer if payer is not None and payer.kind == "player" else team_acct
    if recipient.id == a.account_id:
        raise ConflictError(f"{a.account.name}'s share is already covered by the amount they paid.")
    try:
        with db.begin_nested():
            tr = _make_transfer(db, t.team_id, a.account, recipient, amount_due,
                                f"Collection for #{t.id}", actor)
            s = m.Settlement(kind="collection", transaction_id=t.id, account_id=a.account_id,
                             allocation_id=a.id, amount=amount_due,
                             settlement_transaction_id=tr.id, status="active")
            db.add(s)
            a.settlement_status = 1 if q2(already_collected + already_credited + amount_due) >= a.allocated_amount else 0
            a.settled_transaction_id = tr.id
            db.flush()
            _finalize_team_balance_rounding(db, t, actor)
    except IntegrityError:
        raise ConflictError(f"{a.account.name} has already paid this.")
    log(db, actor, "settlement.collect", "transaction", t.id, t.team_id,
        {"from": a.account.name, "to": recipient.name, "amount": amount_due, "transfer_id": tr.id})
    return s


def _reverse_credit_applications(db: Session, allocation: m.Allocation, actor: str) -> None:
    movements = db.scalars(select(m.PlayerCreditMovement).where(
        m.PlayerCreditMovement.allocation_id == allocation.id,
        m.PlayerCreditMovement.kind == "application",
        m.PlayerCreditMovement.reversed_at.is_(None))).all()
    for movement in movements:
        movement.reversed_at = m.utcnow()
        credit = db.get(m.PlayerCredit, movement.credit_id)
        if credit is not None:
            credit.remaining_amount = q2(min(credit.original_amount,
                                              credit.remaining_amount + movement.amount))
            log(db, actor, "player_credit.application_reverse", "player_credit", credit.id,
                credit.team_id, {"allocation_id": allocation.id, "amount": movement.amount})


def _reconcile_credit_applications(db: Session, allocation: m.Allocation,
                                   new_amount: Decimal, actor: str) -> None:
    """Keep credit applied to an allocation at or below its revised amount after cash collections."""
    cash_paid = _active_collected(db, allocation)
    allowed = q2(max(ZERO, new_amount - cash_paid))
    applied = _applied_credit(db, allocation)
    excess = q2(applied - allowed)
    if excess <= ZERO:
        return
    movements = db.scalars(select(m.PlayerCreditMovement).where(
        m.PlayerCreditMovement.allocation_id == allocation.id,
        m.PlayerCreditMovement.kind == "application",
        m.PlayerCreditMovement.reversed_at.is_(None)).order_by(
        m.PlayerCreditMovement.id.desc())).all()
    for movement in movements:
        if excess <= ZERO:
            break
        credit = db.get(m.PlayerCredit, movement.credit_id)
        movement.reversed_at = m.utcnow()
        if credit is not None:
            credit.remaining_amount = q2(min(credit.original_amount,
                                              credit.remaining_amount + movement.amount))
        if movement.amount > excess:
            replacement_amount = q2(movement.amount - excess)
            if credit is not None:
                credit.remaining_amount = q2(credit.remaining_amount - replacement_amount)
                db.add(m.PlayerCreditMovement(
                    credit_id=movement.credit_id, kind="application", amount=replacement_amount,
                    transaction_id=allocation.transaction_id, allocation_id=allocation.id))
            excess = ZERO
        else:
            excess = q2(excess - movement.amount)
        if credit is not None:
            log(db, actor, "player_credit.application_adjust", "player_credit", credit.id,
                credit.team_id, {"allocation_id": allocation.id, "reversed_amount": movement.amount})


def _upsert_player_credit(db: Session, team_id: int, account_id: int, source_transaction_id: int,
                          amount: Decimal, note: str, actor: str) -> m.PlayerCredit:
    """Keep one outstanding credit per source transaction and player account."""
    amount = q2(amount)
    if amount <= ZERO:
        raise LedgerError("Credit amount must be positive.")
    credit = db.scalar(select(m.PlayerCredit).where(
        m.PlayerCredit.source_transaction_id == source_transaction_id,
        m.PlayerCredit.account_id == account_id).with_for_update())
    if credit is None:
        credit = m.PlayerCredit(team_id=team_id, account_id=account_id,
                                source_transaction_id=source_transaction_id,
                                original_amount=amount, remaining_amount=amount, note=note)
        db.add(credit)
        db.flush()
        db.add(m.PlayerCreditMovement(credit_id=credit.id, kind="created", amount=amount,
                                      transaction_id=source_transaction_id))
    else:
        # Credits already used/transferred are immutable history; only increase the remaining
        # amount when a later edit creates additional overpayment.
        delta = q2(amount - credit.original_amount)
        if delta > ZERO:
            credit.original_amount = q2(credit.original_amount + delta)
            credit.remaining_amount = q2(credit.remaining_amount + delta)
            credit.note = note
            db.add(m.PlayerCreditMovement(credit_id=credit.id, kind="adjustment", amount=delta,
                                          transaction_id=source_transaction_id))
    log(db, actor, "player_credit.create", "player_credit", credit.id, team_id,
        {"account_id": account_id, "amount": amount, "source_transaction_id": source_transaction_id})
    return credit


def player_credit_balance(db: Session, account_id: int) -> Decimal:
    return q2(db.scalar(select(func.coalesce(func.sum(m.PlayerCredit.remaining_amount), 0)).where(
        m.PlayerCredit.account_id == account_id)))


def apply_player_credit(db: Session, credit_id: int, allocation_id: int, actor: str) -> Decimal:
    """Explicitly apply credit to a player's future allocation; never auto-applied."""
    credit = db.scalar(select(m.PlayerCredit).where(m.PlayerCredit.id == credit_id).with_for_update())
    allocation = db.scalar(select(m.Allocation).where(m.Allocation.id == allocation_id).with_for_update())
    if credit is None or allocation is None:
        raise NotFoundError("Credit or allocation not found.")
    if credit.account_id != allocation.account_id or credit.team_id != allocation.transaction.team_id:
        raise ConflictError("Credit and allocation must belong to the same player and team.")
    if allocation.transaction.status != "active" or allocation.transaction.type != "expense":
        raise ConflictError("Credit can only be applied to an active expense allocation.")
    remaining_due = q2(max(ZERO, allocation.allocated_amount - _active_collected(db, allocation)
                           - _applied_credit(db, allocation)))
    amount = q2(min(credit.remaining_amount, remaining_due))
    if amount <= ZERO:
        raise ConflictError("No credit or outstanding amount is available to apply.")
    credit.remaining_amount = q2(credit.remaining_amount - amount)
    db.add(m.PlayerCreditMovement(credit_id=credit.id, kind="application", amount=amount,
                                  transaction_id=allocation.transaction_id, allocation_id=allocation.id))
    # Credit is not a cash transfer; a separate application movement makes the offset explicit.
    if q2(_active_collected(db, allocation) + _applied_credit(db, allocation)) >= allocation.allocated_amount:
        allocation.settlement_status = 1
    log(db, actor, "player_credit.apply", "player_credit", credit.id, credit.team_id,
        {"allocation_id": allocation.id, "amount": amount})
    return amount


def transfer_player_credit_to_team(db: Session, credit_id: int, actor: str) -> Decimal:
    credit = db.scalar(select(m.PlayerCredit).where(m.PlayerCredit.id == credit_id).with_for_update())
    if credit is None or credit.remaining_amount <= ZERO:
        raise ConflictError("No available player credit to transfer.")
    account = db.get(m.Account, credit.account_id)
    if account is None or account.kind != "player":
        raise ConflictError("Only player credits can be transferred to the team account.")
    team_account = get_team_account(db, credit.team_id)
    amount = q2(credit.remaining_amount)
    tr = _make_transfer(db, credit.team_id, account, team_account, amount,
                        f"Player credit transferred to team (credit #{credit.id})", actor)
    credit.remaining_amount = ZERO
    db.add(m.PlayerCreditMovement(credit_id=credit.id, kind="team_transfer", amount=amount,
                                  transaction_id=tr.id))
    log(db, actor, "player_credit.transfer", "player_credit", credit.id, credit.team_id,
        {"amount": amount, "transfer_id": tr.id})
    return amount


def _applied_credit(db: Session, allocation: m.Allocation) -> Decimal:
    return q2(db.scalar(select(func.coalesce(func.sum(m.PlayerCreditMovement.amount), 0)).where(
        m.PlayerCreditMovement.allocation_id == allocation.id,
        m.PlayerCreditMovement.kind == "application",
        m.PlayerCreditMovement.reversed_at.is_(None))))


def _active_collected(db: Session, allocation: m.Allocation) -> Decimal:
    return q2(db.scalar(select(func.coalesce(func.sum(m.Settlement.amount), 0)).where(
        m.Settlement.allocation_id == allocation.id,
        m.Settlement.kind == "collection", m.Settlement.status == "active")))

def _finalize_team_balance_rounding(db: Session, t: m.Transaction, actor: str) -> None:
    """Move the rounded-up difference into team balance once all player shares are collected."""
    if t.type != "expense" or t.status != "active" or not t.surplus_amount:
        return
    if db.scalar(select(m.Settlement.id).where(
        m.Settlement.transaction_id == t.id, m.Settlement.kind == "team_balance",
        m.Settlement.status == "active")):
        return
    if any(a.account.kind == "player" and a.settlement_status == 0 for a in t.allocations):
        return
    payer = _payer_account(t)
    if payer is None or payer.kind != "player":
        return
    team_acct = get_team_account(db, t.team_id)
    tr = _make_transfer(db, t.team_id, payer, team_acct, t.surplus_amount,
                        f"Team balance rounding for #{t.id}", actor)
    db.add(m.Settlement(kind="team_balance", transaction_id=t.id, account_id=team_acct.id,
                        amount=t.surplus_amount, settlement_transaction_id=tr.id, status="active"))
    db.flush()


def collect_all(db: Session, txn_id: int, actor: str) -> int:
    t = db.get(m.Transaction, txn_id)
    if t is None:
        raise NotFoundError("Transaction not found.")
    ids = [a.id for a in t.allocations if a.settlement_status == 0 and a.account.kind == "player"]
    if not ids:
        raise ConflictError("Nothing left to collect on this transaction.")
    for i in ids:
        collect(db, i, actor)
    return len(ids)


def _reverse_row(db: Session, s: m.Settlement, actor: str, reason: str | None) -> None:
    now = m.utcnow()
    tr = db.get(m.Transaction, s.settlement_transaction_id) if s.settlement_transaction_id else None
    if tr is not None and tr.status == "active":
        tr.status = "reversed"
        tr.voided_at, tr.voided_by, tr.void_reason = now, actor, reason or "Settlement reversed"
    s.status = "reversed"
    s.reversed_at = now
    if s.allocation_id:
        al = db.get(m.Allocation, s.allocation_id)
        if al is not None:
            collected = _active_collected(db, al)
            applied = _applied_credit(db, al)
            al.settlement_status = 1 if q2(collected + applied) >= al.allocated_amount else 0
            if al.settlement_status:
                last = db.scalar(select(m.Settlement).where(
                    m.Settlement.allocation_id == al.id, m.Settlement.kind == "collection",
                    m.Settlement.status == "active").order_by(m.Settlement.id.desc()))
                al.settled_transaction_id = last.settlement_transaction_id if last else None
            else:
                al.settled_transaction_id = None
    parent = db.get(m.Transaction, s.transaction_id)
    log(db, actor, "settlement.reverse", "settlement", s.id, parent.team_id if parent else None,
        {"kind": s.kind, "amount": s.amount, "parent": s.transaction_id, "batch": s.batch_id, "reason": reason})


def _active_group(db: Session, s: m.Settlement) -> list[m.Settlement]:
    """A net settlement is one batch: its rows are reversed together."""
    if s.batch_id:
        rows = list(db.scalars(select(m.Settlement).where(m.Settlement.batch_id == s.batch_id,
                                                          m.Settlement.status == "active")
                               .order_by(m.Settlement.id).execution_options(populate_existing=True)).all())
        parent_ids = {row.transaction_id for row in rows}
        if any(row.kind == "collection" for row in rows):
            rounding = db.scalars(select(m.Settlement).where(
                m.Settlement.transaction_id.in_(parent_ids),
                m.Settlement.kind == "team_balance", m.Settlement.status == "active")).all()
            rows.extend(rounding)
        return rows
    rows = [s]
    if s.kind == "collection":
        # A collection reversal also reverses the dependent team-balance adjustment.
        rounding = db.scalars(select(m.Settlement).where(
            m.Settlement.transaction_id == s.transaction_id,
            m.Settlement.kind == "team_balance", m.Settlement.status == "active")).all()
        rows.extend(rounding)
    elif s.kind == "team_balance":
        # Reversing the adjustment invalidates the full set of collections that triggered it.
        collections = db.scalars(select(m.Settlement).where(
            m.Settlement.transaction_id == s.transaction_id,
            m.Settlement.kind == "collection", m.Settlement.status == "active")).all()
        rows.extend(collections)
    return rows


def _lock_all(db: Session, ids) -> None:
    for i in sorted(set(ids)):
        _lock_txn(db, i)


def reverse_settlement(db: Session, settlement_id: int, actor: str, reason: str | None = None) -> int:
    s0 = db.get(m.Settlement, settlement_id)
    if s0 is None:
        raise NotFoundError("Settlement not found.")
    _lock_all(db, [s0.transaction_id] + [g.transaction_id for g in _active_group(db, s0)])
    s = db.scalar(select(m.Settlement).where(m.Settlement.id == settlement_id)
                  .with_for_update().execution_options(populate_existing=True))
    if s.status != "active":
        raise ConflictError("This settlement is already reversed.")
    group = _active_group(db, s)
    for row in group:
        _reverse_row(db, row, actor, reason)
    return len(group)


def void_transaction(db: Session, txn_id: int, actor: str, reason: str | None = None) -> str:
    """Voiding a settlement transfer reverses that settlement. Voiding a parent reverses its settlements."""
    reason = (reason or "").strip()[:200] or None
    link = settlement_for_transfer(db, txn_id)
    if link is not None:
        reverse_settlement(db, link.id, actor, reason)
        return "settlement reversed"
    credit_transfer = db.scalar(select(m.PlayerCreditMovement).where(
        m.PlayerCreditMovement.transaction_id == txn_id,
        m.PlayerCreditMovement.kind == "team_transfer",
        m.PlayerCreditMovement.reversed_at.is_(None)))
    if credit_transfer is not None:
        transfer = _lock_txn(db, txn_id)
        if transfer.status != "active":
            raise ConflictError("This credit transfer is already reversed.")
        transfer.status = "reversed"
        transfer.voided_at, transfer.voided_by = m.utcnow(), actor
        transfer.void_reason = (reason or "Player credit transfer reversed")[:200]
        credit_transfer.reversed_at = m.utcnow()
        credit = db.get(m.PlayerCredit, credit_transfer.credit_id)
        if credit is not None:
            credit.remaining_amount = q2(min(credit.original_amount,
                                              credit.remaining_amount + credit_transfer.amount))
        log(db, actor, "player_credit.transfer_reverse", "player_credit",
            credit_transfer.credit_id, credit.team_id if credit else None,
            {"amount": credit_transfer.amount, "transfer_id": txn_id, "reason": reason})
        return "player credit transfer reversed"
    linked = db.scalars(select(m.Settlement).where(m.Settlement.transaction_id == txn_id,
                                                   m.Settlement.status == "active")).all()
    ids = {txn_id}
    for s in linked:
        ids.update(g.transaction_id for g in _active_group(db, s))
    _lock_all(db, ids)
    t = _lock_txn(db, txn_id)
    if t.status != "active":
        raise ConflictError("This transaction is already voided or reversed.")
    # A credit created by this expense cannot survive voiding its source while used elsewhere.
    source_credits = db.scalars(select(m.PlayerCredit).where(
        m.PlayerCredit.source_transaction_id == txn_id).with_for_update()).all()
    for credit in source_credits:
        active_usage = db.scalar(select(func.count()).select_from(m.PlayerCreditMovement).where(
            m.PlayerCreditMovement.credit_id == credit.id,
            m.PlayerCreditMovement.kind.in_(("application", "team_transfer")),
            m.PlayerCreditMovement.reversed_at.is_(None)))
        if active_usage:
            raise ConflictError("Reverse this credit's applications or team transfer before voiding its source transaction.")
        credit.remaining_amount = ZERO
        for movement in db.scalars(select(m.PlayerCreditMovement).where(
            m.PlayerCreditMovement.credit_id == credit.id,
            m.PlayerCreditMovement.kind == "created",
            m.PlayerCreditMovement.reversed_at.is_(None))).all():
            movement.reversed_at = m.utcnow()

    t.status = "voided"
    t.voided_at, t.voided_by, t.void_reason = m.utcnow(), actor, reason
    # Restore any credit applied to this now-voided expense.
    for allocation in t.allocations:
        movements = db.scalars(select(m.PlayerCreditMovement).where(
            m.PlayerCreditMovement.allocation_id == allocation.id,
            m.PlayerCreditMovement.kind == "application",
            m.PlayerCreditMovement.reversed_at.is_(None))).all()
        for movement in movements:
            movement.reversed_at = m.utcnow()
            credit = db.get(m.PlayerCredit, movement.credit_id)
            if credit is not None:
                credit.remaining_amount = q2(min(credit.original_amount,
                                                  credit.remaining_amount + movement.amount))
    seen: set[int] = set()
    for s in linked:
        for row in _active_group(db, s):
            if row.id not in seen and row.status == "active":
                seen.add(row.id)
                _reverse_row(db, row, actor, "Parent transaction voided")
    db.flush()
    log(db, actor, "transaction.void", "transaction", t.id, t.team_id,
        {"reason": reason, "amount": t.amount, "type": t.type})
    return "voided"


# ---------------------------------------------------------------- pending and net settlement

def pending_positions(db: Session, team_id: int) -> dict[int, dict]:
    """Outstanding player shares and unreimbursed player-fronted expenses."""
    out: dict[int, dict] = {}

    def slot(aid):
        return out.setdefault(aid, {"owed": ZERO, "owed_n": 0, "reimb": ZERO, "reimb_n": 0, "net": ZERO})

    allocs = db.scalars(select(m.Allocation).join(m.Transaction, m.Transaction.id == m.Allocation.transaction_id)
        .join(m.Account, m.Account.id == m.Allocation.account_id)
        .where(m.Transaction.team_id == team_id, m.Transaction.status == "active",
               m.Transaction.type == "expense", m.Account.kind == "player",
               m.Allocation.settlement_status == 0)).all()
    owed_by_account: dict[int, list[Decimal]] = {}
    for allocation in allocs:
        due = q2(max(ZERO, allocation.allocated_amount - _active_collected(db, allocation)
                     - _applied_credit(db, allocation)))
        if due > ZERO:
            owed_by_account.setdefault(allocation.account_id, []).append(due)
    for aid, amounts in owed_by_account.items():
        slot(aid).update(owed=q2(sum(amounts, ZERO)), owed_n=len(amounts))

    reimbursed = exists().where(m.Settlement.transaction_id == m.Transaction.id,
                                m.Settlement.kind == "reimbursement", m.Settlement.status == "active")
    for aid, total, n in db.execute(
            select(m.TransactionAccount.account_id, func.sum(m.Transaction.amount), func.count())
            .join(m.Transaction, m.Transaction.id == m.TransactionAccount.transaction_id)
            .join(m.Account, m.Account.id == m.TransactionAccount.account_id)
            .where(m.Transaction.team_id == team_id, m.Transaction.status == "active",
                   m.Transaction.type == "expense", m.TransactionAccount.role == "paid_by",
                   m.Account.kind == "player", ~reimbursed)
            .group_by(m.TransactionAccount.account_id)).all():
        slot(aid).update(reimb=q2(total), reimb_n=n)
    for v in out.values():
        v["net"] = q2(v["reimb"] - v["owed"])
    return out

def team_pending_totals(pending: dict) -> dict:
    reimb = sum((v["reimb"] for v in pending.values()), ZERO)
    owed = sum((v["owed"] for v in pending.values()), ZERO)
    return {"reimb": reimb, "owed": owed, "net": q2(reimb - owed)}


def pending_of(pending: dict | None, account_id: int | None) -> dict:
    empty = {"owed": ZERO, "owed_n": 0, "reimb": ZERO, "reimb_n": 0, "net": ZERO}
    return (pending or {}).get(account_id, empty)


def _pending_items(db: Session, acct: m.Account):
    reimbursed = exists().where(m.Settlement.transaction_id == m.Transaction.id,
                                m.Settlement.kind == "reimbursement", m.Settlement.status == "active")
    exps = db.scalars(
        select(m.Transaction).join(m.TransactionAccount, m.TransactionAccount.transaction_id == m.Transaction.id)
        .where(m.TransactionAccount.role == "paid_by", m.TransactionAccount.account_id == acct.id,
               m.Transaction.status == "active", m.Transaction.type == "expense", ~reimbursed)
        .order_by(m.Transaction.id).execution_options(populate_existing=True)).all()
    allocs = db.scalars(
        select(m.Allocation).join(m.Transaction, m.Transaction.id == m.Allocation.transaction_id)
        .where(m.Allocation.account_id == acct.id, m.Allocation.settlement_status == 0,
               m.Transaction.status == "active", m.Transaction.type == "expense")
        .order_by(m.Allocation.id).execution_options(populate_existing=True)).all()
    return list(exps), list(allocs)


def settle_net(db: Session, player_id: int, actor: str) -> dict:
    """Settle everything pending for a player with ONE transfer for the difference.
    Reimbursements and collections are marked settled together and reverse together."""
    p = db.get(m.Player, player_id)
    if p is None:
        raise NotFoundError("Player not found.")
    acct = p.account
    exps, allocs = _pending_items(db, acct)
    if not exps and not allocs:
        raise ConflictError(f"Nothing is pending for {p.player_name}.")
    _lock_all(db, [t.id for t in exps] + [a.transaction_id for a in allocs])
    exps, allocs = _pending_items(db, acct)
    if not exps and not allocs:
        raise ConflictError(f"Nothing is pending for {p.player_name}.")
    reimb_total = sum((t.amount for t in exps), ZERO)
    coll_total = sum((q2(max(ZERO, a.allocated_amount - _active_collected(db, a) - _applied_credit(db, a)))
                      for a in allocs), ZERO)
    net = q2(reimb_total - coll_total)
    team_acct = get_team_account(db, p.team_id)
    batch = uuid.uuid4().hex
    try:
        with db.begin_nested():
            tr = None
            note = f"Net settlement for {p.player_name}"
            if net > 0:
                tr = _make_transfer(db, p.team_id, team_acct, acct, net, note, actor)
            elif net < 0:
                tr = _make_transfer(db, p.team_id, acct, team_acct, -net, note, actor)
            first = True
            for t in exps:
                db.add(m.Settlement(kind="reimbursement", transaction_id=t.id, account_id=acct.id, amount=t.amount,
                                    settlement_transaction_id=tr.id if (tr and first) else None,
                                    batch_id=batch, status="active"))
                first = False
            for a in allocs:
                db.add(m.Settlement(kind="collection", transaction_id=a.transaction_id, account_id=acct.id,
                                    allocation_id=a.id,
                                    amount=q2(max(ZERO, a.allocated_amount - _active_collected(db, a) - _applied_credit(db, a))),
                                    settlement_transaction_id=tr.id if (tr and first) else None,
                                    batch_id=batch, status="active"))
                first = False
                a.settlement_status = 1
                a.settled_transaction_id = tr.id if tr else None
            db.flush()
    except IntegrityError:
        raise ConflictError("Something on this player was settled at the same time. Reload and try again.")
    log(db, actor, "settlement.net", "player", p.id, p.team_id,
        {"net": net, "reimbursed": reimb_total, "collected": coll_total, "items": len(exps) + len(allocs),
         "batch": batch, "transfer_id": tr.id if tr else None})
    return {"net": net, "reimbursed": reimb_total, "collected": coll_total, "items": len(exps) + len(allocs),
            "player": p.player_name}


# ---------------------------------------------------------------- balances

def _sum_by_account(db: Session, team_id: int, *, role: str, types: tuple[str, ...]) -> dict[int, Decimal]:
    rows = db.execute(
        select(m.TransactionAccount.account_id, func.coalesce(func.sum(m.Transaction.amount), 0))
        .join(m.Transaction, m.Transaction.id == m.TransactionAccount.transaction_id)
        .where(m.Transaction.team_id == team_id, m.Transaction.status == "active",
               m.Transaction.type.in_(types), m.TransactionAccount.role == role)
        .group_by(m.TransactionAccount.account_id)).all()
    return {r[0]: q2(r[1]) for r in rows}


def account_positions(db: Session, team_id: int) -> dict[int, dict[str, Decimal]]:
    """owed = allocations. paid = expenses/income paid + transfers out - transfers in."""
    owed = {r[0]: q2(r[1]) for r in db.execute(
        select(m.Allocation.account_id, func.coalesce(func.sum(m.Allocation.allocated_amount), 0))
        .join(m.Transaction, m.Transaction.id == m.Allocation.transaction_id)
        .where(m.Transaction.team_id == team_id, m.Transaction.status == "active")
        .group_by(m.Allocation.account_id)).all()}
    fronted = _sum_by_account(db, team_id, role="paid_by", types=("expense", "income"))
    t_out = _sum_by_account(db, team_id, role="account_out", types=("transfer",))
    t_in = _sum_by_account(db, team_id, role="account_in", types=("transfer",))
    ids = set(owed) | set(fronted) | set(t_out) | set(t_in)
    out = {}
    for i in ids:
        paid = fronted.get(i, ZERO) + t_out.get(i, ZERO) - t_in.get(i, ZERO)
        out[i] = {"owed": owed.get(i, ZERO), "paid": paid, "net": owed.get(i, ZERO) - paid}
    return out


def player_balances(db: Session, team_id: int, include_archived: bool = False) -> list[dict]:
    q = (select(m.Player).options(selectinload(m.Player.account)).where(m.Player.team_id == team_id))
    if not include_archived:
        q = q.where(m.Player.status == "active")
    players = db.scalars(q).all()
    pos = account_positions(db, team_id)
    rows = []
    for p in players:
        x = pos.get(p.account.id, {"owed": ZERO, "paid": ZERO, "net": ZERO})
        rows.append({"player": p, **x})
    rows.sort(key=lambda r: (-r["net"], r["player"].player_name.lower()))
    return rows


def opening_balance(db: Session, team_id: int) -> Decimal:
    acct = get_team_account(db, team_id)
    ob = db.scalar(select(m.OpeningBalance).where(m.OpeningBalance.account_id == acct.id))
    return q2(ob.amount) if ob else ZERO


def team_summary(db: Session, team_id: int) -> dict:
    def total(kind: str) -> Decimal:
        return q2(db.scalar(select(func.coalesce(func.sum(m.Transaction.amount), 0)).where(
            m.Transaction.team_id == team_id, m.Transaction.status == "active", m.Transaction.type == kind)))

    total_in, total_out = total("income"), total("expense")
    acct = get_team_account(db, team_id)
    t_in = _sum_by_account(db, team_id, role="account_in", types=("transfer",)).get(acct.id, ZERO)
    t_out = _sum_by_account(db, team_id, role="account_out", types=("transfer",)).get(acct.id, ZERO)
    team_paid = _sum_by_account(db, team_id, role="paid_by", types=("expense",)).get(acct.id, ZERO)
    opening = opening_balance(db, team_id)
    balance = opening + total_in + t_in - t_out - team_paid
    cats = db.execute(
        select(m.Category.name, func.sum(m.Transaction.amount))
        .join(m.Transaction, m.Transaction.category_id == m.Category.id)
        .where(m.Transaction.team_id == team_id, m.Transaction.status == "active",
               m.Transaction.type == "expense")
        .group_by(m.Category.name).order_by(func.sum(m.Transaction.amount).desc())).all()
    by_category = [(n, q2(v)) for n, v in cats if q2(v) > 0]
    return {"total_in": total_in, "total_out": total_out, "balance": balance, "opening": opening,
            "transfers_in": t_in, "transfers_out": t_out, "paid_by_team": team_paid,
            "by_category": by_category}


def player_history(db: Session, player: m.Player) -> tuple[list[dict], Decimal]:
    """Every event touching the player's account with a running net (owed - paid)."""
    acct = player.account
    tx = db.scalars(
        select(m.Transaction).options(selectinload(m.Transaction.accounts), selectinload(m.Transaction.allocations),
                                      selectinload(m.Transaction.category))
        .where(m.Transaction.team_id == player.team_id).order_by(m.Transaction.transaction_date, m.Transaction.id)).all()
    settle = db.scalars(select(m.Settlement).where(m.Settlement.transaction_id.in_([t.id for t in tx]) if tx else False)).all()
    by_transfer = {s.settlement_transaction_id: s for s in settle if s.settlement_transaction_id}
    active_by_parent: dict[tuple[int, str], m.Settlement] = {}
    for s in settle:
        if s.status == "active":
            active_by_parent[(s.transaction_id, s.kind)] = s
    events = []
    credit_moves = db.scalars(select(m.PlayerCreditMovement).join(
        m.PlayerCredit, m.PlayerCredit.id == m.PlayerCreditMovement.credit_id
    ).where(m.PlayerCredit.account_id == acct.id,
            m.PlayerCreditMovement.kind == "application",
            m.PlayerCreditMovement.reversed_at.is_(None))).all()
    credit_by_txn: dict[int, list[m.PlayerCreditMovement]] = {}
    for movement in credit_moves:
        if movement.transaction_id:
            credit_by_txn.setdefault(movement.transaction_id, []).append(movement)
    for t in tx:
        roles = {(ta.role, ta.account_id) for ta in t.accounts}
        alloc = next((a for a in t.allocations if a.account_id == acct.id), None)
        active = t.status == "active"
        if alloc:
            events.append({"t": t, "role": "Owed", "delta": alloc.allocated_amount if active else ZERO,
                           "amount": alloc.allocated_amount, "alloc": alloc,
                           "settled": alloc.settlement_status == 1})
        for movement in credit_by_txn.get(t.id, []):
            events.append({"t": t, "role": "Credit applied", "delta": ZERO,
                           "amount": movement.amount, "credit_movement": movement})
        if ("paid_by", acct.id) in roles:
            s = active_by_parent.get((t.id, "reimbursement"))
            events.append({"t": t, "role": "Paid", "delta": -t.amount if active else ZERO, "amount": t.amount,
                           "reimburse": t.type == "expense", "settled": s is not None, "settlement": s})
        if ("account_out", acct.id) in roles:
            s = by_transfer.get(t.id)
            events.append({"t": t, "role": ("Net settlement paid" if s and s.batch_id else
                                            "Collected from player" if s and s.kind == "collection" else "Transfer out"),
                           "delta": -t.amount if active else ZERO, "amount": t.amount, "link": s})
        if ("account_in", acct.id) in roles:
            s = by_transfer.get(t.id)
            events.append({"t": t, "role": ("Net settlement received" if s and s.batch_id else
                                            "Reimbursed" if s and s.kind == "reimbursement" else "Transfer in"),
                           "delta": t.amount if active else ZERO, "amount": t.amount, "link": s})
    running = ZERO
    for e in events:
        running += e["delta"]
        e["running"] = running
    return events, running


# ---------------------------------------------------------------- data reset

def reset_data(db: Session, actor: str, *, since: dt.datetime | None) -> dict:
    """Hard-delete ledger rows (all, or created at/after `since`). audit_log is never touched."""
    cond = (m.Transaction.created_at >= since) if since else (m.Transaction.id > 0)
    ids = select(m.Transaction.id).where(cond)
    reset_ids = set(db.scalars(ids).all())
    n_txn = len(reset_ids)
    # Net-settlement batches touching anything being deleted are removed whole, reopening what survives.
    credit_movements = db.scalars(select(m.PlayerCreditMovement).where(
        m.PlayerCreditMovement.transaction_id.in_(ids),
        m.PlayerCreditMovement.kind.in_(("application", "team_transfer")),
        m.PlayerCreditMovement.reversed_at.is_(None))).all()
    for movement in credit_movements:
        credit = db.get(m.PlayerCredit, movement.credit_id)
        if credit is not None:
            credit.remaining_amount = q2(min(credit.original_amount,
                                              credit.remaining_amount + movement.amount))
    db.flush()
    batch_rows = db.scalars(select(m.Settlement).where(m.Settlement.batch_id.in_(
        select(m.Settlement.batch_id).where(m.Settlement.batch_id.is_not(None),
                                            m.Settlement.transaction_id.in_(ids)
                                            | m.Settlement.settlement_transaction_id.in_(ids))))).all()
    for s_ in batch_rows:
        if s_.allocation_id:
            al = db.get(m.Allocation, s_.allocation_id)
            if al:
                al.settlement_status, al.settled_transaction_id = 0, None
    db.flush()
    for s_ in batch_rows:
        db.delete(s_)
    db.flush()
    # Settlement transfers being removed whose parent stays: put the parent back to unsettled.
    orphaned = db.scalars(select(m.Settlement).where(
        m.Settlement.settlement_transaction_id.in_(ids), m.Settlement.transaction_id.not_in(ids))).all()
    for s in orphaned:
        if s.allocation_id and s.status == "active":
            a = db.get(m.Allocation, s.allocation_id)
            if a:
                a.settlement_status, a.settled_transaction_id = 0, None
    db.flush()
    credit_ids = select(m.PlayerCredit.id).where(m.PlayerCredit.source_transaction_id.in_(ids))
    # If a source transaction is reset, reopen surviving allocations that used its credit.
    source_applications = db.scalars(select(m.PlayerCreditMovement).where(
        m.PlayerCreditMovement.credit_id.in_(credit_ids),
        m.PlayerCreditMovement.kind == "application",
        m.PlayerCreditMovement.reversed_at.is_(None),
        m.PlayerCreditMovement.allocation_id.is_not(None))).all()
    for movement in source_applications:
        allocation = db.get(m.Allocation, movement.allocation_id)
        if allocation is None or allocation.transaction_id in reset_ids:
            continue
        other_credit = q2(db.scalar(select(func.coalesce(func.sum(m.PlayerCreditMovement.amount), 0)).where(
            m.PlayerCreditMovement.allocation_id == allocation.id,
            m.PlayerCreditMovement.kind == "application",
            m.PlayerCreditMovement.reversed_at.is_(None),
            m.PlayerCreditMovement.credit_id.not_in(credit_ids))))
        allocation.settlement_status = 1 if (
            _active_collected(db, allocation) + other_credit >= allocation.allocated_amount) else 0
        if allocation.settlement_status == 0:
            allocation.settled_transaction_id = None
    db.flush()
    db.execute(delete(m.PlayerCreditMovement).where(
        m.PlayerCreditMovement.credit_id.in_(credit_ids)
        | m.PlayerCreditMovement.transaction_id.in_(ids)), execution_options=NOSYNC)
    db.execute(delete(m.PlayerCredit).where(m.PlayerCredit.source_transaction_id.in_(ids)), execution_options=NOSYNC)
    db.flush()
    db.execute(update(m.Allocation).where(m.Allocation.settled_transaction_id.in_(ids))
               .values(settled_transaction_id=None, settlement_status=0), execution_options=NOSYNC)
    db.execute(delete(m.Settlement).where(m.Settlement.transaction_id.in_(ids)
                                          | m.Settlement.settlement_transaction_id.in_(ids)), execution_options=NOSYNC)
    db.execute(delete(m.Allocation).where(m.Allocation.transaction_id.in_(ids)), execution_options=NOSYNC)
    db.execute(delete(m.TransactionAccount).where(m.TransactionAccount.transaction_id.in_(ids)), execution_options=NOSYNC)
    db.execute(delete(m.Transaction).where(cond), execution_options=NOSYNC)
    db.expire_all()
    log(db, actor, "data.reset", "system", None, None,
        {"scope": "since" if since else "all", "since": since, "transactions_deleted": n_txn})
    return {"transactions": n_txn}
