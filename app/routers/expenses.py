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
    create_team_expense, update_team_expense, delete_team_expense,
)
from ..services.category_service import list_expense_categories
from ..services.player_service import get_players_sorted

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
    players = get_players_sorted(db, team.id, active_only=True)
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
    return templates.TemplateResponse("expense_detail.html", {"request": request, "team": team, "expense": expense})


@router.get("/expenses/{expense_id}/edit")
def edit_expense_form(expense_id: int, request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    expense = db.query(models.TeamExpense).get(expense_id)
    players = get_players_sorted(db, team.id, active_only=True)
    categories = [c.name for c in list_expense_categories(db, team.id)]
    return templates.TemplateResponse("expense_edit.html", {
        "request": request, "team": team, "expense": expense, "players": players, "categories": categories,
    })


@router.post("/expenses/{expense_id}/edit")
def edit_expense_submit(
    expense_id: int, request: Request, category: str = Form(...), amount: float = Form(...),
    payment_source: str = Form(...), paid_by_player_id: int = Form(None), db: Session = Depends(get_db),
):
    team = get_current_team(db)
    try:
        update_team_expense(db, expense_id, category, amount, payment_source, paid_by_player_id)
    except ValueError as e:
        expense = db.query(models.TeamExpense).get(expense_id)
        players = get_players_sorted(db, team.id, active_only=True)
        categories = [c.name for c in list_expense_categories(db, team.id)]
        return templates.TemplateResponse("expense_edit.html", {
            "request": request, "team": team, "expense": expense, "players": players,
            "categories": categories, "error": str(e),
        })
    return RedirectResponse(f"/expenses/{expense_id}", status_code=303)


@router.post("/expenses/{expense_id}/delete")
def delete_expense_submit(expense_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        delete_team_expense(db, expense_id)
    except ValueError as e:
        team = get_current_team(db)
        expense = db.query(models.TeamExpense).get(expense_id)
        return templates.TemplateResponse("expense_detail.html", {
            "request": request, "team": team, "expense": expense, "error": str(e),
        })
    return RedirectResponse("/expenses", status_code=303)
