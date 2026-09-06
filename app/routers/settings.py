from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from .. import models
from ..auth import require_admin
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.team_service import reset_all_data, reset_data_before
from ..services.category_service import list_expense_categories, list_income_types

IST_OFFSET = timedelta(hours=5, minutes=30)

router = APIRouter(dependencies=[Depends(require_admin)])

THEME_GROUPS = {
    "Light": ["light", "sky", "sandstone", "blossom", "seafoam", "linen"],
    "Dark": ["dark", "cricket-green", "midnight", "maroon", "royal-blue", "monochrome", "luxury-gold"],
    "Vibrant": ["sunset", "neon", "tropical", "electric-violet", "citrus"],
}


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    return templates.TemplateResponse("settings.html", {
        "request": request, "team": team, "theme_groups": THEME_GROUPS,
        "current_theme": request.cookies.get("ehcc_theme", "dark"),
        "expense_categories": list_expense_categories(db, team.id),
        "income_types": list_income_types(db, team.id),
        "default_cutoff": "2026-09-06T18:30",
    })


@router.post("/settings/reset-before")
def reset_before(request: Request, cutoff: str = Form(...), confirmation_text: str = Form(""), db: Session = Depends(get_db)):
    team = get_current_team(db)
    if confirmation_text.strip().upper() != "RESET":
        return templates.TemplateResponse("settings.html", {
            "request": request, "team": team, "theme_groups": THEME_GROUPS,
            "current_theme": request.cookies.get("ehcc_theme", "dark"),
            "expense_categories": list_expense_categories(db, team.id),
            "income_types": list_income_types(db, team.id),
            "default_cutoff": cutoff,
            "reset_before_error": 'Type "RESET" exactly to confirm - nothing was deleted.',
        })
    # cutoff is a naive datetime-local string, treated as IST (team's timezone)
    cutoff_ist = datetime.fromisoformat(cutoff)
    cutoff_utc = cutoff_ist - IST_OFFSET
    reset_data_before(db, team.id, cutoff_utc)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/expense-categories")
def add_expense_category(name: str = Form(...), db: Session = Depends(get_db)):
    team = get_current_team(db)
    name = name.strip()
    exists = db.query(models.ExpenseCategory).filter(
        models.ExpenseCategory.team_id == team.id, models.ExpenseCategory.name == name
    ).first()
    if name and not exists:
        db.add(models.ExpenseCategory(team_id=team.id, name=name))
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/expense-categories/{category_id}/edit")
def edit_expense_category(category_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    category = db.query(models.ExpenseCategory).get(category_id)
    if category and name.strip():
        category.name = name.strip()
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/expense-categories/{category_id}/delete")
def delete_expense_category(category_id: int, db: Session = Depends(get_db)):
    category = db.query(models.ExpenseCategory).get(category_id)
    if category:
        db.delete(category)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/income-types")
def add_income_type(name: str = Form(...), db: Session = Depends(get_db)):
    team = get_current_team(db)
    name = name.strip()
    exists = db.query(models.IncomeType).filter(
        models.IncomeType.team_id == team.id, models.IncomeType.name == name
    ).first()
    if name and not exists:
        db.add(models.IncomeType(team_id=team.id, name=name))
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/income-types/{type_id}/edit")
def edit_income_type(type_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    income_type = db.query(models.IncomeType).get(type_id)
    if income_type and name.strip():
        income_type.name = name.strip()
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/income-types/{type_id}/delete")
def delete_income_type(type_id: int, db: Session = Depends(get_db)):
    income_type = db.query(models.IncomeType).get(type_id)
    if income_type:
        db.delete(income_type)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/reset-data")
def reset_data(request: Request, confirmation_text: str = Form(""), db: Session = Depends(get_db)):
    team = get_current_team(db)
    if confirmation_text.strip().upper() != "RESET":
        return templates.TemplateResponse("settings.html", {
            "request": request, "team": team, "theme_groups": THEME_GROUPS,
            "current_theme": request.cookies.get("ehcc_theme", "dark"),
            "expense_categories": list_expense_categories(db, team.id),
            "income_types": list_income_types(db, team.id),
            "default_cutoff": "2026-09-06T18:30",
            "reset_error": 'Type "RESET" exactly to confirm - nothing was deleted.',
        })
    reset_all_data(db)
    return RedirectResponse("/setup", status_code=303)
