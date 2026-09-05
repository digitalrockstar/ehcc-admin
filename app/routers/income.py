from fastapi import APIRouter, Depends, Request, Form
from ..auth import require_admin
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.expense_service import add_adhoc_income

router = APIRouter(dependencies=[Depends(require_admin)])

DEFAULT_TYPES = ["Team Contribution", "Sponsorship", "Donation", "Miscellaneous Income"]


@router.get("/income")
def list_income(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    income = db.query(models.AdHocIncome).filter(models.AdHocIncome.team_id == team.id).order_by(
        models.AdHocIncome.date.desc()
    ).all()
    types = {i.name for i in db.query(models.IncomeType).filter(
        models.IncomeType.team_id == team.id)} | set(DEFAULT_TYPES)
    return templates.TemplateResponse("income.html", {
        "request": request, "team": team, "income": income, "types": sorted(types),
    })


@router.post("/income")
def add_income(
    date: str = Form(...), income_type: str = Form(...), amount: float = Form(...),
    notes: str = Form(None), db: Session = Depends(get_db),
):
    team = get_current_team(db)
    add_adhoc_income(db, team.id, date, income_type, amount, notes=notes)
    return RedirectResponse("/income", status_code=303)
