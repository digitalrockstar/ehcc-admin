from datetime import date as date_type
from fastapi import APIRouter, Depends, Request, Form
from ..auth import require_admin
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import List
from .. import models
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.expense_service import (
    create_team_expense, allocate_expense_to_players, pay_expense_allocation,
)
from ..services.category_service import list_expense_categories

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/expenses")
def list_expenses(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    expenses = db.query(models.TeamExpense).filter(models.TeamExpense.team_id == team.id).order_by(
        models.TeamExpense.date.desc()
    ).all()
    return templates.TemplateResponse("expenses.html", {"request": request, "team": team, "expenses": expenses})


@router.get("/expenses/new")
def new_expense_form(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    players = db.query(models.Player).filter(
        models.Player.team_id == team.id, models.Player.status == models.PlayerStatus.active
    ).all()
    categories = [c.name for c in list_expense_categories(db, team.id)]
    return templates.TemplateResponse("expense_new.html", {
        "request": request, "team": team, "players": players, "categories": categories,
    })


@router.post("/expenses")
def create_expense_submit(
    date: date_type = Form(...), category: str = Form(...), amount: float = Form(...),
    payment_source: str = Form(...), paid_by_player_id: int = Form(None), db: Session = Depends(get_db),
):
    team = get_current_team(db)
    expense = create_team_expense(db, team.id, date, category, amount, payment_source, paid_by_player_id)
    return RedirectResponse(f"/expenses/{expense.id}", status_code=303)


@router.get("/expenses/{expense_id}")
def expense_detail(expense_id: int, request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    expense = db.query(models.TeamExpense).get(expense_id)
    players = db.query(models.Player).filter(
        models.Player.team_id == team.id, models.Player.status == models.PlayerStatus.active
    ).all()
    recovered = sum(float(a.amount) for a in expense.allocations if a.status == models.PaymentStatus.paid)
    recoverable = sum(float(a.amount) for a in expense.allocations)
    return templates.TemplateResponse("expense_detail.html", {
        "request": request, "team": team, "expense": expense, "players": players,
        "recovered": recovered, "recoverable": recoverable, "outstanding": recoverable - recovered,
    })


@router.post("/expenses/{expense_id}/allocate")
def allocate(expense_id: int, player_ids_in_order: List[int] = Form(...), db: Session = Depends(get_db)):
    allocate_expense_to_players(db, expense_id, player_ids_in_order)
    return RedirectResponse(f"/expenses/{expense_id}", status_code=303)


@router.post("/expense-allocations/{allocation_id}/pay")
def pay_allocation(allocation_id: int, db: Session = Depends(get_db)):
    alloc = pay_expense_allocation(db, allocation_id)
    return RedirectResponse(f"/expenses/{alloc.expense_id}", status_code=303)
