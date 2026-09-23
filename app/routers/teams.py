from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_admin
from .. import models
from ..services.ledger_service import team_account, log

router = APIRouter()


@router.post("/team-switch")
def switch_team(request: Request, team_id: int = Form(...)):
    destination = request.headers.get("referer", "/")
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie("ehcc_team", str(team_id), max_age=60 * 60 * 24 * 365)
    return response


@router.post("/settings/teams")
def create_team(name: str = Form(...), starting_balance: str = Form("0"),
                 db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    try:
        bal = Decimal(starting_balance or "0")
    except InvalidOperation:
        bal = Decimal(0)
    team = models.Team(name=name.strip(), starting_balance=bal)
    db.add(team)
    db.flush()
    team_account(db, team)  # Section 4: team + its account are created together
    log(db, "admin", "create", "team", team.id, name)
    db.commit()
    response = RedirectResponse("/settings", status_code=303)
    response.set_cookie("ehcc_team", str(team.id), max_age=60 * 60 * 24 * 365)
    return response


@router.post("/settings/teams/{team_id}/edit")
def edit_team(team_id: int, name: str = Form(...), starting_balance: str = Form(...),
              db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    team = db.query(models.Team).get(team_id)
    if team:
        team.name = name.strip()
        try:
            team.starting_balance = Decimal(starting_balance)
        except InvalidOperation:
            pass
        log(db, "admin", "edit", "team", team.id)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/teams/{team_id}/archive")
def archive_team(team_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    team = db.query(models.Team).get(team_id)
    if team:
        team.is_archived = True
        log(db, "admin", "archive", "team", team.id)
        db.commit()
    return RedirectResponse("/settings", status_code=303)
