from fastapi import APIRouter, Depends, Request
from ..auth import require_admin
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.expense_service import reimburse_player_for_expense

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/reimbursements")
def list_reimbursements(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    due_expenses = db.query(models.TeamExpense).filter(
        models.TeamExpense.team_id == team.id,
        models.TeamExpense.reimbursement_status == models.ReimbursementStatus.due,
    ).all()
    history = db.query(models.Reimbursement).join(models.TeamExpense).filter(
        models.TeamExpense.team_id == team.id
    ).order_by(models.Reimbursement.date.desc()).all()
    return templates.TemplateResponse("reimbursements.html", {
        "request": request, "team": team, "due_expenses": due_expenses, "history": history,
    })


@router.post("/reimbursements/{expense_id}")
def reimburse(expense_id: int, db: Session = Depends(get_db)):
    reimburse_player_for_expense(db, expense_id)
    return RedirectResponse("/reimbursements", status_code=303)
