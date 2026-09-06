import os
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from . import models

templates = Jinja2Templates(directory="app/templates")

# Cache-busting for themes.css: without this, browsers can hold onto a
# stale cached copy after a deploy since the URL never changes, which
# looks exactly like "the theme didn't change anything" even though the
# server-side cookie/HTML is correct.
_css_path = os.path.join(os.path.dirname(__file__), "static", "themes.css")
templates.env.globals["css_version"] = str(int(os.path.getmtime(_css_path))) if os.path.exists(_css_path) else "1"


def get_current_team(db: Session) -> models.Team:
    """Single-team MVP: use the first team created. Multi-team support is
    a documented future expansion (Section 47) and this is the one seam
    to change when that lands."""
    return db.query(models.Team).order_by(models.Team.id).first()
