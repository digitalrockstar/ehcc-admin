import csv
import io
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_admin
from ..deps import templates, get_selected_team, all_teams
from .. import models
from ..services.ledger_service import player_account, player_totals, log

router = APIRouter()


@router.get("/players")
def list_players(request: Request, db: Session = Depends(get_db)):
    team = get_selected_team(request, db)
    rows = []
    if team:
        players = db.query(models.Player).filter_by(team_id=team.id, is_archived=False).all()
        for p in players:
            totals = player_totals(db, p)
            rows.append({"player": p, **totals})
        rows.sort(key=lambda r: r["net_outstanding"], reverse=True)
    return templates.TemplateResponse("players.html", {
        "request": request, "team": team, "teams": all_teams(db), "rows": rows,
    })


@router.post("/players")
def add_player(request: Request, player_name: str = Form(...), mob_no: str = Form(""),
               db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    team = get_selected_team(request, db)
    if team:
        p = models.Player(team_id=team.id, player_name=player_name.strip(), mob_no=mob_no.strip() or None)
        db.add(p)
        db.flush()
        player_account(db, p)
        log(db, "admin", "create", "player", p.id, player_name)
        db.commit()
    return RedirectResponse(f"/players?team_id={team.id if team else ''}", status_code=303)


@router.post("/players/{player_id}/edit")
def edit_player(player_id: int, player_name: str = Form(...), mob_no: str = Form(""),
                 db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    p = db.query(models.Player).get(player_id)
    if p:
        p.player_name = player_name.strip()
        p.mob_no = mob_no.strip() or None
        log(db, "admin", "edit", "player", p.id)
        db.commit()
    return RedirectResponse(f"/players/{player_id}", status_code=303)


@router.post("/players/{player_id}/archive")
def archive_player(player_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    p = db.query(models.Player).get(player_id)
    team_id = p.team_id if p else ""
    if p:
        p.is_archived = True
        log(db, "admin", "archive", "player", p.id)
        db.commit()
    return RedirectResponse(f"/players?team_id={team_id}", status_code=303)


@router.post("/players/{player_id}/delete")
def delete_player(player_id: int, db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    p = db.query(models.Player).get(player_id)
    team_id = p.team_id if p else ""
    if p:
        acc = db.query(models.Account).filter_by(kind="player", player_id=p.id).first()
        has_history = acc and db.query(models.Allocation).filter_by(account_id=acc.id).first()
        if has_history:
            p.is_archived = True  # never hard-delete a player with financial history
        else:
            if acc:
                db.delete(acc)
            db.delete(p)
        log(db, "admin", "delete", "player", player_id)
        db.commit()
    return RedirectResponse(f"/players?team_id={team_id}", status_code=303)


@router.post("/players/import-csv")
def import_csv(request: Request, file: UploadFile = File(...),
                db: Session = Depends(get_db), _: bool = Depends(require_admin)):
    team = get_selected_team(request, db)
    if team:
        content = file.file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            name = (row.get("player_name") or row.get("name") or "").strip()
            if not name:
                continue
            mob = (row.get("mob_no") or row.get("mobile") or "").strip() or None
            p = models.Player(team_id=team.id, player_name=name, mob_no=mob)
            db.add(p)
            db.flush()
            player_account(db, p)
        log(db, "admin", "csv-import", "player", None, file.filename)
        db.commit()
    return RedirectResponse(f"/players?team_id={team.id if team else ''}", status_code=303)


@router.get("/players/{player_id}")
def player_detail(player_id: int, request: Request, db: Session = Depends(get_db)):
    p = db.query(models.Player).get(player_id)
    team = p.team if p else get_selected_team(request, db)
    totals = player_totals(db, p) if p else {}
    return templates.TemplateResponse("player_detail.html", {
        "request": request, "team": team, "teams": all_teams(db), "player": p, "totals": totals,
    })
