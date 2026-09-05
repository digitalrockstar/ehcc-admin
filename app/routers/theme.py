from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

router = APIRouter()

VALID_THEMES = {
    "dark", "light", "cricket-green", "midnight", "maroon", "royal-blue", "monochrome", "luxury-gold",
}


@router.post("/theme")
def set_theme(request: Request, theme: str = Form(...)):
    theme = theme if theme in VALID_THEMES else "dark"
    destination = request.headers.get("referer", "/")
    response = RedirectResponse(destination, status_code=303)
    # 1 year, so the choice persists between sessions per Section 41
    response.set_cookie("ehcc_theme", theme, max_age=60 * 60 * 24 * 365)
    return response
