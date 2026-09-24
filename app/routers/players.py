from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_db
from ..formatting import inr
from ..security import admin_form, admin_name
from ..services import ledger, masters
from ..services.ledger import LedgerError
from ..web import flash, page, redirect, resolve_team

router = APIRouter()


@router.get("/players")
def players(request: Request, show: str = "active", db: Session = Depends(get_db)):
    team = resolve_team(request, db)
    if team is None:
        return page(request, db, "players.html", team=None, rows=[])
    rows = ledger.player_balances(db, team.id, include_archived=(show == "archived"))
    if show == "archived":
        rows = [r for r in rows if r["player"].status == "archived"]
    return page(request, db, "players.html", team=team, rows=rows, show=show)


@router.get("/players/{player_id}")
def player_detail(player_id: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(m.Player, player_id)
    if p is None:
        raise HTTPException(404, "Player not found.")
    team = resolve_team(request, db, force=p.team)
    events, net = ledger.player_history(db, p)
    owed = sum((e["delta"] for e in events if e["role"] == "Owed"), ledger.ZERO)
    pend = ledger.pending_of(ledger.pending_positions(db, p.team_id), p.account.id)
    return page(request, db, "player_detail.html", team=team, player=p, events=events, net=net,
                owed=owed, paid=owed - net, pend=pend, teambar_path="/players")


def _team_from(form, db):
    tid = str(form.get("team_id", ""))
    team = db.get(m.Team, int(tid)) if tid.isdigit() else None
    if team is None:
        raise HTTPException(400, "Choose a team.")
    return team


def _run(request, form, db, action, msg, default_next="/players"):
    try:
        result = action()
        db.commit()
        flash(request, msg(result) if callable(msg) else msg)
    except LedgerError as e:
        db.rollback()
        flash(request, str(e), "err")
    return redirect(request, form, default_next)


@router.post("/players/add")
def add(request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    team = _team_from(form, db)
    return _run(request, form, db, lambda: masters.create_player(
        db, team.id, form.get("player_name"), form.get("mob_no"), admin_name(request)), "Player added.")


@router.post("/players/import")
async def import_csv(request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    team = _team_from(form, db)
    up = form.get("file")
    if not isinstance(up, UploadFile) and not hasattr(up, "read"):
        flash(request, "Choose a CSV file.", "err")
        return redirect(request, form, "/players")
    raw = await up.read()

    def action():
        res = masters.import_players_csv(db, team.id, raw, admin_name(request))
        return res

    try:
        res = action()
        db.commit()
    except LedgerError as e:
        db.rollback()
        flash(request, str(e), "err")
        return redirect(request, form, "/players")
    flash(request, f"Imported {res['added']} players, skipped {res['skipped']} duplicates.")
    for err in res["errors"][:5]:
        flash(request, err, "err")
    return redirect(request, form, "/players")


@router.post("/players/{player_id}/settle-net")
def settle_net(player_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    def msg(r):
        who, net = r["player"], r["net"]
        if net > 0:
            return f"Net settlement done. The team paid {who} {inr(net)} in one transfer."
        if net < 0:
            return f"Net settlement done. {who} paid the team {inr(-net)} in one transfer."
        return f"Settled {r['items']} items with no cash movement. What the team owed {who} and what {who} owed the team cancel out."
    return _run(request, form, db, lambda: ledger.settle_net(db, player_id, admin_name(request)), msg,
                f"/players/{player_id}")


@router.post("/players/{player_id}/edit")
def edit(player_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _run(request, form, db, lambda: masters.update_player(
        db, player_id, form.get("player_name"), form.get("mob_no"), admin_name(request)), "Player updated.")


@router.post("/players/{player_id}/archive")
def archive(player_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    archived = form.get("archive") == "1"
    return _run(request, form, db, lambda: masters.set_player_archived(db, player_id, archived, admin_name(request)),
                "Player archived." if archived else "Player restored.")


@router.post("/players/{player_id}/delete")
def delete(player_id: int, request: Request, form=Depends(admin_form), db: Session = Depends(get_db)):
    return _run(request, form, db, lambda: masters.delete_player(db, player_id, admin_name(request)), "Player deleted.")
