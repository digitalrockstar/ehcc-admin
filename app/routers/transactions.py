from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from ..auth import require_admin
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.team_service import get_activity

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/transactions")
def list_transactions(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    activity = get_activity(db, team.id)
    return templates.TemplateResponse("transactions.html", {"request": request, "team": team, "activity": activity})
