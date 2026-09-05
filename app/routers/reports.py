from fastapi import APIRouter, Depends, Request
from ..auth import require_admin
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.match_service import get_match_financials
from ..services.player_service import list_players_with_balances

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/reports")
def reports(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)

    player_rows = list_players_with_balances(db, team.id)

    matches = db.query(models.Match).filter(models.Match.team_id == team.id).all()
    match_rows = [{"match": m, **get_match_financials(db, m.id)} for m in matches]

    return templates.TemplateResponse("reports.html", {
        "request": request, "team": team, "player_rows": player_rows, "match_rows": match_rows,
    })
