from decimal import Decimal, InvalidOperation
from datetime import date as date_cls
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_admin
from ..deps import templates, get_selected_team, all_teams
from .. import models
from ..services import ledger_service as ledger

router = APIRouter()


def _party_options(db: Session, team: models.Team):
    tacc = ledger.team_account(db, team)
    players = db.query(models.Player).filter_by(team_id=team.id, is_archived=False).order_by(models.Player.player_name).all()
    options = [{"id": tacc.id, "label": f"{team.name} (team account)"}]
    for p in players:
        options.append({"id": ledger.player_account(db, p).id, "label": p.player_name})
    return options


@router.get("/transactions")
def list_transactions(request: Request, db: Session = Depends(get_db)):
    team = get_selected_team(request, db)
    txns = []
    if team:
        txns = (
            db.query(models.Transaction)
            .filter_by(team_id=team.id)
            .order_by(models.Transaction.transaction_date.desc(), models.Transaction.id.desc())
            .all()
        )
    return templates.TemplateResponse("transactions.html", {
        "request": request, "team": team, "teams": all_teams(db), "txns": txns,
    })


@router.get("/transactions/new")
def new_transaction_form(request: Request, db: Session = Depends(get_db)):
    team = get_selected_team(request, db)
    income_cats = db.query(models.Category).filter_by(type="income", is_archived=False).all()
    expense_cats = db.query(models.Category).filter_by(type="expense", is_archived=False).all()
    parties = _party_options(db, team) if team else []
    return templates.TemplateResponse("transaction_form.html", {
        "request": request, "team": team, "teams": all_teams(db),
        "income_cats": income_cats, "expense_cats": expense_cats, "parties": parties,
        "today": date_cls.today().isoformat(),
    })


@router.post("/transactions")
def create_transaction(
    request: Request,
    team_id: int = Form(...),
    transaction_date: str = Form(...),
    type: str = Form(...),
    category_id: str = Form(""),
    item_description: str = Form(""),
    amount: str = Form(...),
    payer_account_id: str = Form(""),
    to_account_id: str = Form(""),
    charged_to: list[str] = Form([]),
    db: Session = Depends(get_db),
    _: bool = Depends(require_admin),
):
    team = db.query(models.Team).get(team_id)
    try:
        amt = Decimal(amount)
    except InvalidOperation:
        amt = Decimal(0)
    tdate = date_cls.fromisoformat(transaction_date)
    cat_id = int(category_id) if category_id else None
    tacc = ledger.team_account(db, team)

    if type == "income":
        ledger.create_income(
            db, team=team, transaction_date=tdate, category_id=cat_id,
            item_description=item_description, amount=amt,
            payer_account_id=int(payer_account_id) if payer_account_id else None,
            actor="admin",
        )
    elif type == "expense":
        payer = int(payer_account_id) if payer_account_id else tacc.id
        charged_ids = [int(c) for c in charged_to if c]
        ledger.create_expense(
            db, team=team, transaction_date=tdate, category_id=cat_id,
            item_description=item_description, amount=amt, payer_account_id=payer,
            charged_to_account_ids=charged_ids, actor="admin",
        )
    elif type == "transfer":
        ledger.create_transfer(
            db, team=team, transaction_date=tdate,
            from_account_id=int(payer_account_id), to_account_id=int(to_account_id),
            amount=amt, item_description=item_description, actor="admin",
        )
    db.commit()
    return RedirectResponse(f"/transactions?team_id={team.id}", status_code=303)


@router.post("/transactions/{txn_id}/void")
def void_txn(txn_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    txn = db.query(models.Transaction).get(txn_id)
    team_id = txn.team_id if txn else ""
    if txn:
        try:
            ledger.void_transaction(db, txn, actor="admin")
            db.commit()
        except ledger.LedgerError:
            db.rollback()
    return RedirectResponse(f"/transactions?team_id={team_id}", status_code=303)


@router.post("/allocations/{allocation_id}/settle")
def settle(allocation_id: int, request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    alloc = db.query(models.Allocation).get(allocation_id)
    redirect_to = request.headers.get("referer", "/transactions")
    if alloc:
        try:
            ledger.settle_allocation(db, alloc, actor="admin")
            db.commit()
        except ledger.LedgerError:
            db.rollback()
    return RedirectResponse(redirect_to, status_code=303)
