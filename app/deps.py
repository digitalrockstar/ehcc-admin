import os
from datetime import date
from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from . import models

templates = Jinja2Templates(directory="app/templates")

_css_path = os.path.join(os.path.dirname(__file__), "static", "themes.css")
templates.env.globals["css_version"] = str(int(os.path.getmtime(_css_path))) if os.path.exists(_css_path) else "1"
templates.env.globals["today"] = date.today


def get_selected_team(request: Request, db: Session) -> models.Team | None:
    """Every non-Settings screen is scoped to a team (Section 3). Selection
    comes from ?team_id=, falling back to the ehcc_team cookie, falling back
    to the first non-archived team."""
    team_id = request.query_params.get("team_id") or request.cookies.get("ehcc_team")
    team = None
    if team_id:
        team = db.query(models.Team).filter_by(id=team_id, is_archived=False).first()
    if not team:
        team = db.query(models.Team).filter_by(is_archived=False).order_by(models.Team.id).first()
    return team


def all_teams(db: Session):
    return db.query(models.Team).filter_by(is_archived=False).order_by(models.Team.name).all()
