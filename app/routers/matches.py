from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import List
from .. import models
from ..database import get_db
from ..deps import templates, get_current_team
from ..services.match_service import (
    create_match, pay_match_expense_from_account, mark_match_fee_paid, get_match_financials, cancel_match,
)

router = APIRouter()


@router.get("/matches")
def list_matches(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    matches = db.query(models.Match).filter(models.Match.team_id == team.id).order_by(
        models.Match.match_date.desc()
    ).all()
    return templates.TemplateResponse("matches.html", {"request": request, "team": team, "matches": matches})


@router.get("/matches/new")
def new_match_form(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    players = db.query(models.Player).filter(
        models.Player.team_id == team.id, models.Player.status == models.PlayerStatus.active
    ).all()
    return templates.TemplateResponse("match_new.html", {"request": request, "team": team, "players": players})


@router.post("/matches")
def create_match_submit(
    match_date: str = Form(...), ground_fees: float = Form(...), additional_amount: float = Form(0),
    notes: str = Form(None), player_ids: List[int] = Form(...), db: Session = Depends(get_db),
):
    team = get_current_team(db)
    match = create_match(db, team.id, match_date, ground_fees, additional_amount, player_ids, notes)
    return RedirectResponse(f"/matches/{match.id}", status_code=303)


@router.get("/matches/{match_id}")
def match_detail(match_id: int, request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    match = db.query(models.Match).get(match_id)
    financials = get_match_financials(db, match_id)
    return templates.TemplateResponse("match_detail.html", {
        "request": request, "team": team, "match": match, "financials": financials,
    })


@router.post("/matches/{match_id}/pay-expense")
def pay_expense(match_id: int, db: Session = Depends(get_db)):
    pay_match_expense_from_account(db, match_id)
    return RedirectResponse(f"/matches/{match_id}", status_code=303)


@router.post("/matches/{match_id}/cancel")
def cancel(match_id: int, db: Session = Depends(get_db)):
    cancel_match(db, match_id)
    return RedirectResponse(f"/matches/{match_id}", status_code=303)


@router.post("/match-participants/{participant_id}/pay")
def pay_fee(participant_id: int, amount_paid: float = Form(None), db: Session = Depends(get_db)):
    p = mark_match_fee_paid(db, participant_id, amount_paid)
    return RedirectResponse(f"/matches/{p.match_id}", status_code=303)
