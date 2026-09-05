from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from ..auth import require_admin
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.team_service import reset_all_data

router = APIRouter(dependencies=[Depends(require_admin)])

THEMES = ["dark", "light", "cricket-green", "midnight", "maroon", "royal-blue", "monochrome", "luxury-gold"]


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    return templates.TemplateResponse("settings.html", {
        "request": request, "team": team, "themes": THEMES,
        "current_theme": request.cookies.get("ehcc_theme", "dark"),
    })


@router.post("/settings/reset-data")
def reset_data(request: Request, confirmation_text: str = Form(""), db: Session = Depends(get_db)):
    team = get_current_team(db)
    if confirmation_text.strip().upper() != "RESET":
        return templates.TemplateResponse("settings.html", {
            "request": request, "team": team, "themes": THEMES,
            "current_theme": request.cookies.get("ehcc_theme", "dark"),
            "reset_error": 'Type "RESET" exactly to confirm - nothing was deleted.',
        })
    reset_all_data(db)
    return RedirectResponse("/setup", status_code=303)
