"""Turn transactions into display rows shared by the dashboard, list and detail pages."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import models as m
from .ledger import pending_of


def party_label(accts: list[m.Account]) -> str:
    if not accts:
        return "—"
    if len(accts) == 1:
        return accts[0].name
    kind = "players" if all(a.kind == "player" for a in accts) else "parties"
    return f"{len(accts)} {kind}"


def item_label(t: m.Transaction) -> str:
    if t.type == "transfer":
        return t.item_description or "Transfer"
    name = t.category.name if t.category else "—"
    if t.item_description:
        return f"{name}: {t.item_description}" if t.category and t.category.is_other else f"{name} ({t.item_description})"
    return name


def load_transactions_query():
    return select(m.Transaction).options(
        joinedload(m.Transaction.category),
        selectinload(m.Transaction.accounts).joinedload(m.TransactionAccount.account).joinedload(m.Account.player),
        selectinload(m.Transaction.allocations).joinedload(m.Allocation.account).joinedload(m.Account.player),
    )


def describe(db: Session, txns: list[m.Transaction], pending: dict | None = None) -> list[dict]:
    ids = [t.id for t in txns]
    parents: dict[int, list[m.Settlement]] = {}
    links: dict[int, m.Settlement] = {}
    if ids:
        for s in db.scalars(select(m.Settlement).where(m.Settlement.transaction_id.in_(ids))).all():
            if s.status == "active":
                parents.setdefault(s.transaction_id, []).append(s)
        for s in db.scalars(select(m.Settlement).where(m.Settlement.settlement_transaction_id.in_(ids))).all():
            links[s.settlement_transaction_id] = s
    rows = []
    for t in txns:
        paid_by = t.party("paid_by")
        acc_in, acc_out = t.party("account_in"), t.party("account_out")
        if t.type == "expense":
            col1, col2 = party_label(paid_by), party_label([a.account for a in t.allocations])
        elif t.type == "income":
            col1, col2 = (party_label(paid_by) if paid_by else "External"), "—"
        else:
            col1, col2 = party_label(acc_in), party_label(acc_out)
        active = t.status == "active"
        row = {"t": t, "item": item_label(t), "col1": col1, "col2": col2, "link": links.get(t.id),
               "reimb": None, "reimb_s": None, "coll": None}
        if t.type == "expense" and active:
            if paid_by and paid_by[0].kind == "player":
                s = next((x for x in parents.get(t.id, []) if x.kind == "reimbursement"), None)
                row["reimb"], row["reimb_s"] = ("paid" if s else "pay"), s
                if not s:
                    row.update(reimb_warn=pending_of(pending, paid_by[0].id)["owed"], reimb_pid=paid_by[0].player_id,
                               reimb_who=paid_by[0].name)
            player_allocs = [a for a in t.allocations if a.account.kind == "player"]
            if player_allocs:
                who = player_allocs[0].account
                row["coll"] = {"total": len(player_allocs),
                               "done": sum(1 for a in player_allocs if a.settlement_status == 1),
                               "single": player_allocs[0] if len(player_allocs) == 1 else None,
                               "warn": pending_of(pending, who.id)["reimb"] if len(player_allocs) == 1 else 0,
                               "pid": who.player_id, "who": who.name,
                               "single_s": next((x for x in parents.get(t.id, [])
                                                 if x.kind == "collection" and len(player_allocs) == 1), None)}
        rows.append(row)
    return rows
