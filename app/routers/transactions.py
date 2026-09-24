import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_db
from ..security import admin_form, admin_name, require_admin_page
from ..services import ledger
from ..services.ledger import LedgerError, TxnInput
from ..services.masters import parse_amount
from ..services.views import describe, load_transactions_query
from ..web import flash, page, redirect, resolve_team

router = APIRouter()
PAGE_SIZE = 100


def _int(v):
    v = str(v or "").strip()
    return int(v) if v.isdigit() else None


def parse_form(form, team_id: int) -> TxnInput:
    try:
        date = dt.date.fromisoformat(str(form.get("transaction_date", "")))
    except ValueError:
        raise LedgerError("Choose a valid date.")
    return TxnInput(
        team_id=team_id, date=date, type=str(form.get("type", "")), amount=parse_amount(form.get("amount")),
        category_id=_int(form.get("category_id")), item_description=str(form.get("item_description", "")),
        paid_by=_int(form.get("paid_by")), charged_to=[i for i in (_int(x) for x in form.getlist("charged_to")) if i],
        account_in=_int(form.get("account_in")), account_out=_int(form.get("account_out")))


def prefill_from_form(form) -> dict:
    return {"transaction_date": form.get("transaction_date", ""), "type": form.get("type", "expense"),
            "category_id": _int(form.get("category_id")), "item_description": form.get("item_description", ""),
            "amount": form.get("amount", ""), "paid_by": _int(form.get("paid_by")),
            "charged_to": [i for i in (_int(x) for x in form.getlist("charged_to")) if i],
            "account_in": _int(form.get("account_in")), "account_out": _int(form.get("account_out"))}


def prefill_from_txn(t: m.Transaction, keep_date: bool) -> dict:
    def one(role):
        p = t.party(role)
        return p[0].id if p else None
    return {"transaction_date": (t.transaction_date if keep_date else ledger.today_ist()).isoformat(),
            "type": t.type, "category_id": t.category_id, "item_description": t.item_description or "",
            "amount": str(t.amount), "paid_by": one("paid_by"), "charged_to": [a.account_id for a in t.allocations],
            "account_in": one("account_in"), "account_out": one("account_out")}


def form_page(request, db, team, f, *, txn=None, status_code=200, error=None):
    parties = db.scalars(select(m.Account).where(m.Account.team_id == team.id, m.Account.status == "active")).all()
    parties = sorted(parties, key=lambda a: (a.kind != "team", a.name.lower()))
    cats = db.scalars(select(m.Category).order_by(m.Category.sort_order, m.Category.name)).all()
    keep = txn.category_id if txn else None
    cat_json = [{"id": c.id, "name": c.name, "kind": c.kind, "other": c.is_other}
                for c in cats if c.status == "active" or c.id == keep]
    if error:
        flash(request, error, "err")
    return page(request, db, "transaction_form.html", team=team, f=f, txn=txn, parties=parties,
                cat_json=cat_json, step=int(ledger.rounding_step(db)), teambar_path="/transactions",
                status_code=status_code)


@router.get("/transactions")
def list_transactions(request: Request, type: str = "all", show: str = "all", p: int = 1,
                      db: Session = Depends(get_db)):
    team = resolve_team(request, db)
    if team is None:
        return page(request, db, "transactions.html", team=None, rows=[])
    q = load_transactions_query().where(m.Transaction.team_id == team.id)
    cq = select(func.count()).select_from(m.Transaction).where(m.Transaction.team_id == team.id)
    if type in m.TXN_TYPES:
        q, cq = q.where(m.Transaction.type == type), cq.where(m.Transaction.type == type)
    if show == "active":
        q, cq = q.where(m.Transaction.status == "active"), cq.where(m.Transaction.status == "active")
    total = db.scalar(cq)
    p = max(p, 1)
    txns = db.scalars(q.order_by(m.Transaction.transaction_date.desc(), m.Transaction.id.desc())
                      .limit(PAGE_SIZE).offset((p - 1) * PAGE_SIZE)).unique().all()
    return page(request, db, "transactions.html", team=team, rows=describe(db, list(txns)),
                account=ledger.get_team_account(db, team.id), type=type, show=show, p=p,
                pages=max(1, -(-total // PAGE_SIZE)), total=total)


@router.get("/transactions/new")
def new_form(request: Request, copy_from: int | None = None, team_id: int | None = None,
             db: Session = Depends(get_db), _=Depends(require_admin_page)):
    team = resolve_team(request, db, force=db.get(m.Team, team_id) if team_id else None)
    if team is None:
        flash(request, "Create a team in Settings first.", "err")
        return redirect(request, {}, "/settings")
    f = {"transaction_date": ledger.today_ist().isoformat(), "type": "expense", "charged_to": [],
         "amount": "", "item_description": ""}
    if copy_from:
        src = db.scalars(load_transactions_query().where(m.Transaction.id == copy_from)).unique().first()
        if src and src.team_id == team.id:
            f = prefill_from_txn(src, keep_date=False)
    return form_page(request, db, team, f)


@router.post("/transactions/new")
def create(request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    team = db.get(m.Team, int(_int(form.get("team_id")) or 0))
    if team is None:
        raise HTTPException(400, "Choose a team.")
    resolve_team(request, db, force=team)
    try:
        t = ledger.create_transaction(db, parse_form(form, team.id), admin_name(request))
        db.commit()
    except LedgerError as e:
        db.rollback()
        return form_page(request, db, team, prefill_from_form(form), status_code=400, error=str(e))
    flash(request, f"Transaction #{t.id} saved.")
    return redirect(request, form, f"/transactions?team={team.id}")


@router.get("/transactions/{txn_id}/edit")
def edit_form(txn_id: int, request: Request, db: Session = Depends(get_db), _=Depends(require_admin_page)):
    t = db.scalars(load_transactions_query().where(m.Transaction.id == txn_id)).unique().first()
    if t is None:
        raise HTTPException(404, "Transaction not found.")
    team = resolve_team(request, db, force=t.team)
    return form_page(request, db, team, prefill_from_txn(t, keep_date=True), txn=t)


@router.post("/transactions/{txn_id}/edit")
def edit(txn_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    t = db.get(m.Transaction, txn_id)
    if t is None:
        raise HTTPException(404, "Transaction not found.")
    try:
        d = parse_form(form, t.team_id)
        ledger.update_transaction(db, txn_id, d, admin_name(request))
        db.commit()
    except LedgerError as e:
        db.rollback()
        t = db.scalars(load_transactions_query().where(m.Transaction.id == txn_id)).unique().first()
        return form_page(request, db, resolve_team(request, db, force=t.team), prefill_from_form(form),
                         txn=t, status_code=400, error=str(e))
    flash(request, f"Transaction #{txn_id} updated.")
    return redirect(request, form, f"/transactions/{txn_id}")


@router.get("/transactions/{txn_id}")
def detail(txn_id: int, request: Request, db: Session = Depends(get_db)):
    t = db.scalars(load_transactions_query().where(m.Transaction.id == txn_id)).unique().first()
    if t is None:
        raise HTTPException(404, "Transaction not found.")
    team = resolve_team(request, db, force=t.team)
    row = describe(db, [t])[0]
    history = db.scalars(select(m.AuditLog).where(
        ((m.AuditLog.entity_type == "transaction") & (m.AuditLog.entity_id == t.id))
    ).order_by(m.AuditLog.id)).all()
    parent = db.get(m.Transaction, row["link"].transaction_id) if row["link"] else None
    return page(request, db, "transaction_detail.html", team=team, row=row, history=history, parent=parent,
                teambar_path="/transactions")


def _do(request, form, db, action, ok_msg, default_next):
    try:
        result = action()
        db.commit()
    except LedgerError as e:
        db.rollback()
        flash(request, str(e), "err")
        return redirect(request, form, default_next)
    flash(request, ok_msg(result) if callable(ok_msg) else ok_msg)
    return redirect(request, form, default_next)


@router.post("/transactions/{txn_id}/void")
def void(txn_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _do(request, form, db, lambda: ledger.void_transaction(db, txn_id, admin_name(request), form.get("reason")),
               lambda r: f"Transaction #{txn_id} {r}.", f"/transactions/{txn_id}")


@router.post("/transactions/{txn_id}/reimburse")
def reimburse(txn_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _do(request, form, db, lambda: ledger.reimburse(db, txn_id, admin_name(request)),
               "Reimbursed in full.", "/transactions")


@router.post("/transactions/{txn_id}/collect-all")
def collect_all(txn_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _do(request, form, db, lambda: ledger.collect_all(db, txn_id, admin_name(request)),
               lambda n: f"Collected in full from {n} player{'s' if n != 1 else ''}.", f"/transactions/{txn_id}")


@router.post("/allocations/{alloc_id}/collect")
def collect(alloc_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _do(request, form, db, lambda: ledger.collect(db, alloc_id, admin_name(request)),
               "Collected in full.", "/transactions")


@router.post("/settlements/{settlement_id}/reverse")
def reverse(settlement_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _do(request, form, db,
               lambda: ledger.reverse_settlement(db, settlement_id, admin_name(request), form.get("reason")),
               "Settlement reversed.", "/transactions")
