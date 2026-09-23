from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

router = APIRouter()

VALID_THEMES = {
    "dark", "light", "cricket-green", "midnight", "maroon", "royal-blue", "monochrome", "luxury-gold",
    "sky", "sandstone", "blossom", "seafoam", "linen",
    "sunset", "neon", "tropical", "electric-violet", "citrus",
    "crimson-steel", "mint-slate",
}


@router.post("/theme")
def set_theme(request: Request, theme: str = Form(...)):
    theme = theme if theme in VALID_THEMES else "dark"
    destination = request.headers.get("referer", "/")
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie("ehcc_theme", theme, max_age=60 * 60 * 24 * 365)
    return response
