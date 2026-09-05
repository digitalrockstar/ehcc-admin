from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models
from ..database import get_db
from ..deps import templates, get_current_team

router = APIRouter()


@router.get("/players")
def list_players(request: Request, db: Session = Depends(get_db)):
    team = get_current_team(db)
    players = db.query(models.Player).filter(models.Player.team_id == team.id).all()
    return templates.TemplateResponse("players.html", {"request": request, "team": team, "players": players})


@router.post("/players")
def add_player(name: str = Form(...), contact_number: str = Form(None), db: Session = Depends(get_db)):
    team = get_current_team(db)
    db.add(models.Player(team_id=team.id, name=name, contact_number=contact_number or None))
    db.commit()
    return RedirectResponse("/players", status_code=303)


@router.post("/players/{player_id}/toggle-status")
def toggle_status(player_id: int, db: Session = Depends(get_db)):
    player = db.query(models.Player).get(player_id)
    player.status = (
        models.PlayerStatus.inactive if player.status == models.PlayerStatus.active
        else models.PlayerStatus.active
    )
    db.commit()
    return RedirectResponse("/players", status_code=303)


@router.get("/players/{player_id}")
def player_detail(player_id: int, request: Request, db: Session = Depends(get_db)):
    player = db.query(models.Player).get(player_id)
    team = get_current_team(db)

    match_fees = db.query(models.MatchParticipant).filter(models.MatchParticipant.player_id == player_id).all()
    allocations = db.query(models.ExpenseAllocation).filter(models.ExpenseAllocation.player_id == player_id).all()
    expenses_paid = db.query(models.TeamExpense).filter(models.TeamExpense.paid_by_player_id == player_id).all()

    owed_by_player = sum(float(f.fee_amount) for f in match_fees if f.status == models.PaymentStatus.due) + \
        sum(float(a.amount) for a in allocations if a.status == models.PaymentStatus.due)
    owed_to_player = sum(
        float(e.amount) for e in expenses_paid if e.reimbursement_status == models.ReimbursementStatus.due
    )

    return templates.TemplateResponse("player_detail.html", {
        "request": request, "team": team, "player": player, "match_fees": match_fees,
        "allocations": allocations, "expenses_paid": expenses_paid,
        "owed_by_player": owed_by_player, "owed_to_player": owed_to_player,
        "net": owed_to_player - owed_by_player,
    })
