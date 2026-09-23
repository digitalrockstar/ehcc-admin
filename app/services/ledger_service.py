from decimal import Decimal
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import models
from .calculations import per_party_share, allocation_surplus


class LedgerError(Exception):
    pass


# ---------- accounts ----------

def team_account(db: Session, team: models.Team) -> models.Account:
    acc = db.query(models.Account).filter_by(kind="team", team_id=team.id).first()
    if not acc:
        acc = models.Account(kind="team", team_id=team.id)
        db.add(acc)
        db.flush()
    return acc


def player_account(db: Session, player: models.Player) -> models.Account:
    acc = db.query(models.Account).filter_by(kind="player", player_id=player.id).first()
    if not acc:
        acc = models.Account(kind="player", player_id=player.id)
        db.add(acc)
        db.flush()
    return acc


def log(db: Session, actor: str, action: str, entity_type: str, entity_id: int, details: str = None):
    db.add(models.AuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, details=details))


# ---------- creating transactions ----------

def create_income(db: Session, *, team: models.Team, transaction_date: date, category_id: int,
                   item_description: str, amount: Decimal, payer_account_id: int | None, actor: str) -> models.Transaction:
    txn = models.Transaction(
        team_id=team.id, transaction_date=transaction_date, type="income",
        category_id=category_id, item_description=item_description, amount=amount,
        payer_account_id=payer_account_id, recipient_account_id=team_account(db, team).id,
    )
    db.add(txn)
    db.flush()
    log(db, actor, "create", "transaction", txn.id, f"income {amount}")
    return txn


def create_expense(db: Session, *, team: models.Team, transaction_date: date, category_id: int,
                    item_description: str, amount: Decimal, payer_account_id: int,
                    charged_to_account_ids: list[int], actor: str) -> models.Transaction:
    """payer_account_id: team's own account (paid straight from team funds) or a
    single player account (player personally fronted it -> creates a payable).
    charged_to_account_ids: empty/[team account] means the team bears the cost;
    one or more player accounts creates receivable allocations, rounded per
    Section 9 when there's more than one party."""
    tacc = team_account(db, team)
    txn = models.Transaction(
        team_id=team.id, transaction_date=transaction_date, type="expense",
        category_id=category_id, item_description=item_description, amount=amount,
        payer_account_id=payer_account_id,
    )
    db.add(txn)
    db.flush()

    if payer_account_id != tacc.id:
        # a player fronted the money personally -> team owes them the full amount
        db.add(models.Allocation(
            transaction_id=txn.id, account_id=payer_account_id, direction="payable",
            allocated_amount=amount,
        ))

    charged_players = [a for a in charged_to_account_ids if a != tacc.id]
    if charged_players:
        n = len(charged_players)
        if n == 1:
            share = Decimal(amount)
            surplus = Decimal(0)
        else:
            share = per_party_share(amount, n)
            surplus = allocation_surplus(share, n, amount)
        for acc_id in charged_players:
            db.add(models.Allocation(
                transaction_id=txn.id, account_id=acc_id, direction="receivable",
                allocated_amount=share,
            ))
        txn.surplus_amount = surplus

    log(db, actor, "create", "transaction", txn.id, f"expense {amount}")
    return txn


def create_transfer(db: Session, *, team: models.Team, transaction_date: date,
                     from_account_id: int, to_account_id: int, amount: Decimal,
                     item_description: str, actor: str) -> models.Transaction:
    txn = models.Transaction(
        team_id=team.id, transaction_date=transaction_date, type="transfer",
        item_description=item_description, amount=amount,
        payer_account_id=from_account_id, recipient_account_id=to_account_id,
    )
    db.add(txn)
    db.flush()
    log(db, actor, "create", "transaction", txn.id, f"transfer {amount}")
    return txn


# ---------- settlement (Section 10) ----------

def settle_allocation(db: Session, allocation: models.Allocation, actor: str) -> models.Transaction:
    if allocation.settlement_status == 1:
        raise LedgerError("Already settled - duplicate settlement is not allowed.")
    parent = allocation.transaction
    if parent.status != "active":
        raise LedgerError("Cannot settle an allocation on a voided/reversed transaction.")
    tacc = team_account(db, parent.team)

    if allocation.direction == "receivable":
        # player owes team -> collection: player account -> team account
        xfer = create_transfer(
            db, team=parent.team, transaction_date=date.today(),
            from_account_id=allocation.account_id, to_account_id=tacc.id,
            amount=allocation.allocated_amount,
            item_description=f"Collection: {parent.item_description or ''}".strip(), actor=actor,
        )
    else:
        # team owes player -> reimbursement: team account -> player account
        xfer = create_transfer(
            db, team=parent.team, transaction_date=date.today(),
            from_account_id=tacc.id, to_account_id=allocation.account_id,
            amount=allocation.allocated_amount,
            item_description=f"Reimbursement: {parent.item_description or ''}".strip(), actor=actor,
        )

    allocation.settlement_status = 1
    allocation.settled_transaction_id = xfer.id
    log(db, actor, "settle", "allocation", allocation.id)
    return xfer


def unsettle_allocation(db: Session, allocation: models.Allocation, actor: str):
    """Used when the linked settlement transfer is voided/reversed."""
    allocation.settlement_status = 0
    allocation.settled_transaction_id = None
    log(db, actor, "unsettle", "allocation", allocation.id)


# ---------- void / reversal (Section 21) ----------

def void_transaction(db: Session, txn: models.Transaction, actor: str):
    if txn.status != "active":
        raise LedgerError("Only active transactions can be voided.")
    # if this transaction is itself a settlement transfer, unsettle its allocation
    linked = db.query(models.Allocation).filter_by(settled_transaction_id=txn.id).first()
    if linked:
        unsettle_allocation(db, linked, actor)
    # if this transaction has allocations of its own (an expense), any settled
    # ones must be reversed too so money isn't left double-counted
    for alloc in txn.allocations:
        if alloc.settlement_status == 1 and alloc.settled_transaction_id:
            settlement_txn = db.query(models.Transaction).get(alloc.settled_transaction_id)
            if settlement_txn and settlement_txn.status == "active":
                settlement_txn.status = "voided"
                log(db, actor, "void", "transaction", settlement_txn.id, "cascaded from parent void")
        alloc.settlement_status = 0
        alloc.settled_transaction_id = None
    txn.status = "voided"
    log(db, actor, "void", "transaction", txn.id)


# ---------- balances (Section 19) ----------

def _active_sum(db: Session, **filters) -> Decimal:
    q = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter_by(status="active", **filters)
    return Decimal(q.scalar() or 0)


def team_balance(db: Session, team: models.Team) -> Decimal:
    tacc = team_account(db, team)
    income_in = _active_sum(db, type="income", recipient_account_id=tacc.id)
    expense_out = _active_sum(db, type="expense", payer_account_id=tacc.id)
    transfer_in = _active_sum(db, type="transfer", recipient_account_id=tacc.id)
    transfer_out = _active_sum(db, type="transfer", payer_account_id=tacc.id)
    return Decimal(team.starting_balance) + income_in - expense_out + transfer_in - transfer_out


def player_totals(db: Session, player: models.Player) -> dict:
    pacc = player_account(db, player)
    receivables = (
        db.query(models.Allocation)
        .join(models.Transaction, models.Allocation.transaction_id == models.Transaction.id)
        .filter(models.Allocation.account_id == pacc.id, models.Allocation.direction == "receivable",
                models.Transaction.status == "active")
        .all()
    )
    payables = (
        db.query(models.Allocation)
        .join(models.Transaction, models.Allocation.transaction_id == models.Transaction.id)
        .filter(models.Allocation.account_id == pacc.id, models.Allocation.direction == "payable",
                models.Transaction.status == "active")
        .all()
    )
    total_owed = sum((Decimal(a.allocated_amount) for a in receivables), Decimal(0))
    total_paid = sum((Decimal(a.allocated_amount) for a in receivables if a.settlement_status == 1), Decimal(0))
    payable_total = sum((Decimal(a.allocated_amount) for a in payables), Decimal(0))
    payable_settled = sum((Decimal(a.allocated_amount) for a in payables if a.settlement_status == 1), Decimal(0))
    return {
        "total_owed": total_owed,
        "total_paid": total_paid,
        "net_outstanding": total_owed - total_paid,
        "payable_outstanding": payable_total - payable_settled,
        "receivable_allocations": receivables,
        "payable_allocations": payables,
    }
