from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from . import models

templates = Jinja2Templates(directory="app/templates")


def get_current_team(db: Session) -> models.Team:
    """Single-team MVP: use the first team created. Multi-team support is
    a documented future expansion (Section 47) and this is the one seam
    to change when that lands."""
    return db.query(models.Team).order_by(models.Team.id).first()
