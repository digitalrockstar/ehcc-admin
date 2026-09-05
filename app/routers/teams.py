from fastapi import APIRouter, Depends, Request, Form
from ..auth import require_admin
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..deps import templates, get_current_team

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/setup")
def setup_form(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    return templates.TemplateResponse("setup.html", {"request": request, "team": team})


@router.post("/setup")
def setup_submit(request: Request, name: str = Form(...), starting_balance: float = Form(0),
                  db: Session = Depends(get_db)):
    team = get_current_team(db)
    if team:
        team.name = name
        team.starting_balance = starting_balance
    else:
        team = models.Team(name=name, starting_balance=starting_balance)
        db.add(team)
    db.commit()
    return RedirectResponse("/", status_code=303)
