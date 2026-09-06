from fastapi import APIRouter, Depends, Request
from ..auth import require_admin
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.team_service import get_dashboard_summary
from .. import models

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    if not team:
        return RedirectResponse("/setup")
    summary = get_dashboard_summary(db, team.id)
    recent_matches = db.query(models.Match).filter(models.Match.team_id == team.id).order_by(
        models.Match.match_date.desc()
    ).limit(5).all()
    recent_transactions = db.query(models.Transaction).filter(models.Transaction.team_id == team.id).order_by(
        models.Transaction.date.desc(), models.Transaction.id.desc()
    ).limit(10).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "team": team, "summary": summary,
        "recent_matches": recent_matches, "recent_transactions": recent_transactions,
    })
