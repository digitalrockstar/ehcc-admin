"""All financial rules live here: allocation, surplus, settlement, void/reversal, balances."""
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
    """A rule was broken. The message is safe to show to the admin."""


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
        raise LedgerError("This team has no team account.")
    return acct


def _lock_txn(db: Session, txn_id: int) -> m.Transaction:
    t = db.scalar(select(m.Transaction).where(m.Transaction.id == txn_id)
                  .with_for_update().execution_options(populate_existing=True))
    if t is None:
        raise LedgerError("Transaction not found.")
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
            raise LedgerError(f"{a.name} is archived and cannot be used.")
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
        raise LedgerError("Choose a team.")
    if team.status != "active":
        raise LedgerError("This team is archived. Restore it in Settings to add transactions.")
    if d.type not in m.TXN_TYPES:
        raise LedgerError("Choose a transaction type.")
    if not isinstance(d.date, dt.date):
        raise LedgerError("Choose a date.")
    amount = Decimal(d.amount)
    if amount != amount.quantize(TWO):
        raise LedgerError("Amount can have at most 2 decimal places.")
    amount = q2(amount)
    if amount <= 0 or amount > MAX_AMOUNT:
        raise LedgerError("Amount must be a positive value below ₹1,00,00,000.")
    desc = (d.item_description or "").strip() or None
    if desc and len(desc) > 200:
        raise LedgerError("Description is too long (200 characters max).")

    plan = {"team": team, "amount": amount, "desc": desc, "category": None,
            "links": [], "allocs": [], "surplus": ZERO}

    if d.type in ("expense", "income"):
        cat = db.get(m.Category, d.category_id) if d.category_id else None
        if cat is None or cat.kind != d.type:
            raise LedgerError("Choose a category.")
        if cat.status != "active" and cat.id != keep_category_id:
            raise LedgerError(f"Category '{cat.name}' is archived.")
        if cat.is_other and not desc:
            raise LedgerError("Describe the item when the category is 'Other'.")
        plan["category"] = cat

    if d.type == "expense":
        if not d.paid_by:
            raise LedgerError("Choose who paid.")
        (payer,) = _accounts_for_team(db, team.id, [d.paid_by])
        ids = list(dict.fromkeys(d.charged_to))
        if not ids:
            raise LedgerError("Select at least one party to charge.")
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
                raise LedgerError("Income can only be paid in by a player, or left as external.")
            plan["links"].append(("paid_by", payer))
    else:
        if not d.account_in or not d.account_out:
            raise LedgerError("Choose both the account in and the account out.")
        if d.account_in == d.account_out:
            raise LedgerError("Account in and account out must be different.")
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
    for acct, share in plan["allocs"]:
        t.allocations.append(m.Allocation(account_id=acct.id, allocated_amount=share))
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
    t = _lock_txn(db, txn_id)
    if t.status != "active":
        raise LedgerError("Only active transactions can be edited.")
    if settlement_for_transfer(db, t.id):
        raise LedgerError("This transfer was created by a reimbursement or collection. Reverse the settlement instead.")
    if has_active_settlements(db, t.id):
        raise LedgerError("Reverse the reimbursement and collections on this transaction before editing it.")
    if d.type != t.type or d.team_id != t.team_id:
        raise LedgerError("Type and team cannot be changed. Void this transaction and enter a new one.")
    before = snapshot(t)
    plan = _prepare(db, d, keep_category_id=t.category_id)
    t.accounts.clear()
    t.allocations.clear()
    db.flush()
    t.transaction_date = d.date
    t.category_id = plan["category"].id if plan["category"] else None
    t.item_description = plan["desc"]
    t.amount = plan["amount"]
    t.surplus_amount = plan["surplus"]
    for role, acct in plan["links"]:
        t.accounts.append(m.TransactionAccount(account_id=acct.id, role=role))
    for acct, share in plan["allocs"]:
        t.allocations.append(m.Allocation(account_id=acct.id, allocated_amount=share))
    db.flush()
    db.refresh(t)
    log(db, actor, "transaction.edit", "transaction", t.id, t.team_id, {"before": before, "after": snapshot(t)})
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
        raise LedgerError("Only active expenses can be reimbursed.")
    payer = _payer_account(t)
    if payer is None or payer.kind != "player":
        raise LedgerError("Only expenses paid by a player can be reimbursed.")
    exists = db.scalar(select(m.Settlement.id).where(
        m.Settlement.transaction_id == t.id, m.Settlement.account_id == payer.id,
        m.Settlement.kind == "reimbursement", m.Settlement.status == "active"))
    if exists:
        raise LedgerError("This expense has already been reimbursed.")
    team_acct = get_team_account(db, t.team_id)
    try:
        with db.begin_nested():
            tr = _make_transfer(db, t.team_id, team_acct, payer, t.amount, f"Reimbursement for #{t.id}", actor)
            s = m.Settlement(kind="reimbursement", transaction_id=t.id, account_id=payer.id,
                             amount=t.amount, settlement_transaction_id=tr.id, status="active")
            db.add(s)
            db.flush()
    except IntegrityError:
        raise LedgerError("This expense has already been reimbursed.")
    log(db, actor, "settlement.reimburse", "transaction", t.id, t.team_id,
        {"to": payer.name, "amount": t.amount, "transfer_id": tr.id})
    return s


def collect(db: Session, allocation_id: int, actor: str) -> m.Settlement:
    a0 = db.get(m.Allocation, allocation_id)
    if a0 is None:
        raise LedgerError("Allocation not found.")
    t = _lock_txn(db, a0.transaction_id)
    a = db.scalar(select(m.Allocation).where(m.Allocation.id == allocation_id)
                  .with_for_update().execution_options(populate_existing=True))
    if t.type != "expense" or t.status != "active":
        raise LedgerError("Collections apply to active expenses only.")
    if a.account.kind != "player":
        raise LedgerError("Only players are collected from. The team account is charged directly.")
    if a.settlement_status == 1:
        raise LedgerError(f"{a.account.name} has already paid this.")
    team_acct = get_team_account(db, t.team_id)
    try:
        with db.begin_nested():
            tr = _make_transfer(db, t.team_id, a.account, team_acct, a.allocated_amount,
                                f"Collection for #{t.id}", actor)
            s = m.Settlement(kind="collection", transaction_id=t.id, account_id=a.account_id,
                             allocation_id=a.id, amount=a.allocated_amount,
                             settlement_transaction_id=tr.id, status="active")
            db.add(s)
            a.settlement_status = 1
            a.settled_transaction_id = tr.id
            db.flush()
    except IntegrityError:
        raise LedgerError(f"{a.account.name} has already paid this.")
    log(db, actor, "settlement.collect", "transaction", t.id, t.team_id,
        {"from": a.account.name, "amount": a.allocated_amount, "transfer_id": tr.id})
    return s


def collect_all(db: Session, txn_id: int, actor: str) -> int:
    t = db.get(m.Transaction, txn_id)
    if t is None:
        raise LedgerError("Transaction not found.")
    ids = [a.id for a in t.allocations if a.settlement_status == 0 and a.account.kind == "player"]
    if not ids:
        raise LedgerError("Nothing left to collect on this transaction.")
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
            al.settlement_status = 0
            al.settled_transaction_id = None
    parent = db.get(m.Transaction, s.transaction_id)
    log(db, actor, "settlement.reverse", "settlement", s.id, parent.team_id if parent else None,
        {"kind": s.kind, "amount": s.amount, "parent": s.transaction_id, "batch": s.batch_id, "reason": reason})


def _active_group(db: Session, s: m.Settlement) -> list[m.Settlement]:
    """A net settlement is one batch: its rows are reversed together."""
    if s.batch_id:
        return list(db.scalars(select(m.Settlement).where(m.Settlement.batch_id == s.batch_id,
                                                          m.Settlement.status == "active")
                               .order_by(m.Settlement.id).execution_options(populate_existing=True)).all())
    return [s]


def _lock_all(db: Session, ids) -> None:
    for i in sorted(set(ids)):
        _lock_txn(db, i)


def reverse_settlement(db: Session, settlement_id: int, actor: str, reason: str | None = None) -> int:
    s0 = db.get(m.Settlement, settlement_id)
    if s0 is None:
        raise LedgerError("Settlement not found.")
    _lock_all(db, [s0.transaction_id] + [g.transaction_id for g in _active_group(db, s0)])
    s = db.scalar(select(m.Settlement).where(m.Settlement.id == settlement_id)
                  .with_for_update().execution_options(populate_existing=True))
    if s.status != "active":
        raise LedgerError("This settlement is already reversed.")
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
    linked = db.scalars(select(m.Settlement).where(m.Settlement.transaction_id == txn_id,
                                                   m.Settlement.status == "active")).all()
    ids = {txn_id}
    for s in linked:
        ids.update(g.transaction_id for g in _active_group(db, s))
    _lock_all(db, ids)
    t = _lock_txn(db, txn_id)
    if t.status != "active":
        raise LedgerError("This transaction is already voided or reversed.")
    t.status = "voided"
    t.voided_at, t.voided_by, t.void_reason = m.utcnow(), actor, reason
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
    """Per player account: what the team still owes them (unreimbursed expenses they paid)
    and what they still owe the team (uncollected shares)."""
    out: dict[int, dict] = {}

    def slot(aid):
        return out.setdefault(aid, {"owed": ZERO, "owed_n": 0, "reimb": ZERO, "reimb_n": 0, "net": ZERO})

    for aid, total, n in db.execute(
            select(m.Allocation.account_id, func.sum(m.Allocation.allocated_amount), func.count())
            .join(m.Transaction, m.Transaction.id == m.Allocation.transaction_id)
            .join(m.Account, m.Account.id == m.Allocation.account_id)
            .where(m.Transaction.team_id == team_id, m.Transaction.status == "active",
                   m.Transaction.type == "expense", m.Allocation.settlement_status == 0, m.Account.kind == "player")
            .group_by(m.Allocation.account_id)).all():
        slot(aid).update(owed=q2(total), owed_n=n)
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
        v["net"] = v["reimb"] - v["owed"]
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
        raise LedgerError("Player not found.")
    acct = p.account
    exps, allocs = _pending_items(db, acct)
    if not exps and not allocs:
        raise LedgerError(f"Nothing is pending for {p.player_name}.")
    _lock_all(db, [t.id for t in exps] + [a.transaction_id for a in allocs])
    exps, allocs = _pending_items(db, acct)
    if not exps and not allocs:
        raise LedgerError(f"Nothing is pending for {p.player_name}.")
    reimb_total = sum((t.amount for t in exps), ZERO)
    coll_total = sum((a.allocated_amount for a in allocs), ZERO)
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
                                    allocation_id=a.id, amount=a.allocated_amount,
                                    settlement_transaction_id=tr.id if (tr and first) else None,
                                    batch_id=batch, status="active"))
                first = False
                a.settlement_status = 1
                a.settled_transaction_id = tr.id if tr else None
            db.flush()
    except IntegrityError:
        raise LedgerError("Something on this player was settled at the same time. Reload and try again.")
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
    surplus = q2(db.scalar(select(func.coalesce(func.sum(m.Transaction.surplus_amount), 0)).where(
        m.Transaction.team_id == team_id, m.Transaction.status == "active", m.Transaction.type == "expense")))
    cats = db.execute(
        select(m.Category.name, func.sum(m.Transaction.amount))
        .join(m.Transaction, m.Transaction.category_id == m.Category.id)
        .where(m.Transaction.team_id == team_id, m.Transaction.status == "active",
               m.Transaction.type == "expense")
        .group_by(m.Category.name).order_by(func.sum(m.Transaction.amount).desc())).all()
    by_category = [(n, q2(v)) for n, v in cats if q2(v) > 0]
    return {"total_in": total_in, "total_out": total_out, "balance": balance, "opening": opening,
            "transfers_in": t_in, "transfers_out": t_out, "paid_by_team": team_paid,
            "surplus": surplus, "by_category": by_category}


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
    for t in tx:
        roles = {(ta.role, ta.account_id) for ta in t.accounts}
        alloc = next((a for a in t.allocations if a.account_id == acct.id), None)
        active = t.status == "active"
        if alloc:
            events.append({"t": t, "role": "Owed", "delta": alloc.allocated_amount if active else ZERO,
                           "amount": alloc.allocated_amount, "alloc": alloc,
                           "settled": alloc.settlement_status == 1})
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
    n_txn = db.scalar(select(func.count()).select_from(m.Transaction).where(cond))
    # Net-settlement batches touching anything being deleted are removed whole, reopening what survives.
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
