"""Export routes: CSV and PDF downloads for team data and full backup."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..security import require_admin_page
from ..services import export, ledger
from ..services.ledger import NotFoundError
from ..web import page

router = APIRouter()


@router.get("/export/team/{team_id}/csv")
def team_csv_export(team_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(require_admin_page)):
    try:
        csv_data = export.team_csv(db, team_id)
    except NotFoundError:
        return page(request, db, "error.html", status_code=404, code=404, message="Team not found.")
    team = db.get(__import__("app.models", fromlist=["Team"]).Team, team_id)
    filename = f"ehcc_{team.name.replace(' ', '_')}_export.csv"
    return PlainTextResponse(csv_data, media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/team/{team_id}/pdf")
def team_pdf_export(team_id: int, request: Request, db: Session = Depends(get_db),
                    _=Depends(require_admin_page)):
    try:
        ctx = export.team_pdf_context(db, team_id)
    except NotFoundError:
        return page(request, db, "error.html", status_code=404, code=404, message="Team not found.")
    team = db.get(__import__("app.models", fromlist=["Team"]).Team, team_id)
    html = page(request, db, "export_pdf.html", teambar=False, **ctx)
    from weasyprint import HTML
    pdf = HTML(string=html.body.decode()).write_pdf()
    filename = f"ehcc_{team.name.replace(' ', '_')}_report.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/team/{team_id}/players/pdf")
def team_players_pdf_export(team_id: int, request: Request, db: Session = Depends(get_db),
                            _=Depends(require_admin_page)):
    try:
        ctx = export.player_summary_pdf_context(db, team_id)
    except NotFoundError:
        return page(request, db, "error.html", status_code=404, code=404, message="Team not found.")
    team = db.get(__import__("app.models", fromlist=["Team"]).Team, team_id)
    html = page(request, db, "player_summary_pdf.html", teambar=False, **ctx)
    from weasyprint import HTML
    pdf = HTML(string=html.body.decode()).write_pdf()
    filename = f"ehcc_{team.name.replace(' ', '_')}_players_summary.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/full/csv")
def full_csv_export(request: Request, db: Session = Depends(get_db),
                    _=Depends(require_admin_page)):
    csv_data = export.full_backup_csv(db)
    return PlainTextResponse(csv_data, media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="ehcc_full_backup.csv"'})


@router.get("/export/full/pdf")
def full_pdf_export(request: Request, db: Session = Depends(get_db),
                    _=Depends(require_admin_page)):
    ctx = export.full_backup_pdf_context(db)
    html = page(request, db, "export_pdf.html", teambar=False, full_backup=True, **ctx)
    from weasyprint import HTML
    pdf = HTML(string=html.body.decode()).write_pdf()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="ehcc_full_backup.pdf"'})
