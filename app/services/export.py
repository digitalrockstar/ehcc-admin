"""Export team data as CSV (team × player matrix) and PDF (full report)."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import TIMEZONE
from ..formatting import dmy, inr
from . import ledger
from .views import describe, load_transactions_query


def team_csv(db: Session, team_id: int) -> str:
    """Generate a CSV string: one row per transaction, one column per player."""
    team = db.get(m.Team, team_id)
    if team is None:
        raise ledger.NotFoundError("Team not found.")

    players = db.scalars(
        select(m.Player).where(m.Player.team_id == team_id, m.Player.status == "active")
        .order_by(m.Player.player_name)
    ).all()
    player_ids = {p.account.id for p in players}

    txns = db.scalars(
        load_transactions_query().where(m.Transaction.team_id == team_id)
        .order_by(m.Transaction.transaction_date, m.Transaction.id)
    ).unique().all()

    buf = io.StringIO()
    w = csv.writer(buf)

    # Header
    header = ["Date", "Type", "Item / Category", "Description", "Amount (INR)", "Paid By", "Charged To (count)"]
    header.extend(p.player_name for p in players)
    w.writerow(header)

    # Rows
    for t in txns:
        alloc_map = {a.account_id: a.allocated_amount for a in t.allocations}
        charged_count = sum(1 for a in t.allocations if a.account_id in player_ids)
        paid_by = next((ta.account.name for ta in t.accounts if ta.role == "paid_by"), "")
        row = [
            t.transaction_date.isoformat(),
            t.type,
            t.category.name if t.category else "",
            t.item_description or "",
            str(t.amount),
            paid_by,
            str(charged_count),
        ]
        for p in players:
            amt = alloc_map.get(p.account.id, "")
            row.append(str(amt) if amt != "" else "")
        w.writerow(row)

    # Summary section
    w.writerow([])
    w.writerow(["Summary"])
    summary = ledger.team_summary(db, team_id)
    w.writerow(["Total Income", str(summary["total_in"])])
    w.writerow(["Total Expense", str(summary["total_out"])])
    w.writerow(["Team Account Balance", str(summary["balance"])])
    w.writerow(["Surplus", str(summary["surplus"])])
    w.writerow([])
    w.writerow(["Player Balances"])
    w.writerow(["Player", "Owed", "Paid", "Net Outstanding"])
    for r in ledger.player_balances(db, team_id):
        w.writerow([r["player"].player_name, str(r["owed"]), str(r["paid"]), str(r["net"])])

    return buf.getvalue()


def full_backup_csv(db: Session) -> str:
    """Generate a full backup CSV with all teams."""
    teams = db.scalars(select(m.Team).order_by(m.Team.id)).all()
    parts = []
    for team in teams:
        parts.append(f"=== Team: {team.name} (ID: {team.id}) ===")
        parts.append(team_csv(db, team.id))
        parts.append("")
    return "\n".join(parts)


def team_pdf_context(db: Session, team_id: int) -> dict:
    """Build the context for the PDF export template."""
    team = db.get(m.Team, team_id)
    if team is None:
        raise ledger.NotFoundError("Team not found.")

    summary = ledger.team_summary(db, team_id)
    balances = ledger.player_balances(db, team_id)
    txns = db.scalars(
        load_transactions_query().where(m.Transaction.team_id == team_id)
        .order_by(m.Transaction.transaction_date, m.Transaction.id)
    ).unique().all()
    pending = ledger.pending_positions(db, team_id)
    rows = describe(db, list(txns), pending)

    return {
        "team": team,
        "summary": summary,
        "balances": balances,
        "rows": rows,
        "generated_at": datetime.now(TIMEZONE).strftime("%d %b %Y, %I:%M %p IST"),
        "inr": inr,
        "dmy": dmy,
    }


def full_backup_pdf_context(db: Session) -> dict:
    """Build the context for the full backup PDF."""
    teams = db.scalars(select(m.Team).order_by(m.Team.id)).all()
    team_data = []
    for team in teams:
        team_data.append(team_pdf_context(db, team.id))
    return {
        "teams": team_data,
        "generated_at": datetime.now(TIMEZONE).strftime("%d %b %Y, %I:%M %p IST"),
        "inr": inr,
        "dmy": dmy,
    }
