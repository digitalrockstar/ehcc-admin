"""Teams, players, categories and starting defaults."""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from .audit import log
from .ledger import LedgerError, get_team_account, q2, set_setting, get_setting
from ..themes import DEFAULT_THEME

DEFAULT_EXPENSE = ["Ground Charges", "Balls", "Nets", "Gloves", "Bat", "Jerseys", "Stumps", "Adjustment", "Other"]
DEFAULT_INCOME = ["Team Contribution", "Adjustment", "Sponsorship", "Donation", "Misc.", "Other"]


def ensure_defaults(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(m.Category)) == 0:
        for kind, names in (("expense", DEFAULT_EXPENSE), ("income", DEFAULT_INCOME)):
            for i, n in enumerate(names):
                db.add(m.Category(name=n, kind=kind, is_other=(n == "Other"), sort_order=i))
    if get_setting(db, "theme") is None:
        set_setting(db, "theme", DEFAULT_THEME)
    if get_setting(db, "rounding_step") is None:
        set_setting(db, "rounding_step", "5")
    db.commit()


def _clean_name(name: str | None, label: str, limit: int = 80) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        raise LedgerError(f"{label} is required.")
    if len(name) > limit:
        raise LedgerError(f"{label} is too long ({limit} characters max).")
    return name


def parse_amount(raw: str | None, *, allow_negative: bool = False) -> Decimal:
    try:
        v = Decimal((raw or "").replace(",", "").replace("₹", "").strip())
    except InvalidOperation:
        raise LedgerError("Enter a valid amount.")
    if not v.is_finite():
        raise LedgerError("Enter a valid amount.")
    if v < 0 and not allow_negative:
        raise LedgerError("Amount must be positive.")
    return v


# ---------------------------------------------------------------- teams

def create_team(db: Session, name: str, actor: str, opening: Decimal | None = None) -> m.Team:
    name = _clean_name(name, "Team name")
    if db.scalar(select(m.Team.id).where(func.lower(m.Team.name) == name.lower())):
        raise LedgerError(f"A team named '{name}' already exists.")
    team = m.Team(name=name)
    db.add(team)
    db.flush()
    acct = m.Account(team_id=team.id, kind="team")
    db.add(acct)
    db.flush()
    db.add(m.OpeningBalance(account_id=acct.id, amount=q2(opening or 0)))
    db.flush()
    log(db, actor, "team.create", "team", team.id, team.id, {"name": name, "account_id": acct.id})
    return team


def rename_team(db: Session, team_id: int, name: str, actor: str) -> None:
    team = db.get(m.Team, team_id)
    if team is None:
        raise LedgerError("Team not found.")
    name = _clean_name(name, "Team name")
    clash = db.scalar(select(m.Team.id).where(func.lower(m.Team.name) == name.lower(), m.Team.id != team_id))
    if clash:
        raise LedgerError(f"A team named '{name}' already exists.")
    old, team.name = team.name, name
    log(db, actor, "team.rename", "team", team.id, team.id, {"from": old, "to": name})


def set_team_archived(db: Session, team_id: int, archived: bool, actor: str) -> None:
    team = db.get(m.Team, team_id)
    if team is None:
        raise LedgerError("Team not found.")
    team.status = "archived" if archived else "active"
    acct = get_team_account(db, team_id)
    acct.status = team.status
    log(db, actor, "team.archive" if archived else "team.restore", "team", team.id, team.id, {})


def set_opening_balance(db: Session, team_id: int, amount: Decimal, actor: str) -> None:
    acct = get_team_account(db, team_id)
    ob = db.scalar(select(m.OpeningBalance).where(m.OpeningBalance.account_id == acct.id))
    amount = q2(amount)
    if abs(amount) > Decimal("9999999.99"):
        raise LedgerError("Starting balance is out of range.")
    old = q2(ob.amount) if ob else Decimal("0")
    if ob:
        ob.amount = amount
    else:
        db.add(m.OpeningBalance(account_id=acct.id, amount=amount))
    log(db, actor, "team.opening_balance", "team", team_id, team_id, {"from": old, "to": amount})


# ---------------------------------------------------------------- players

_MOB = re.compile(r"^\+?\d{7,15}$")


def clean_mobile(raw: str | None) -> str | None:
    s = re.sub(r"[\s\-().]", "", (raw or ""))
    if not s:
        return None
    if not _MOB.match(s):
        raise LedgerError(f"'{raw}' is not a valid mobile number.")
    return s


def create_player(db: Session, team_id: int, name: str, mob: str | None, actor: str) -> m.Player:
    team = db.get(m.Team, team_id)
    if team is None:
        raise LedgerError("Choose a team.")
    name = _clean_name(name, "Player name")
    mob = clean_mobile(mob)
    if db.scalar(select(m.Player.id).where(m.Player.team_id == team_id,
                                           func.lower(m.Player.player_name) == name.lower())):
        raise LedgerError(f"{name} already exists in {team.name}.")
    p = m.Player(team_id=team_id, player_name=name, mob_no=mob)
    db.add(p)
    db.flush()
    db.add(m.Account(team_id=team_id, kind="player", player_id=p.id))
    db.flush()
    log(db, actor, "player.create", "player", p.id, team_id, {"name": name})
    return p


def update_player(db: Session, player_id: int, name: str, mob: str | None, actor: str) -> None:
    p = db.get(m.Player, player_id)
    if p is None:
        raise LedgerError("Player not found.")
    name = _clean_name(name, "Player name")
    mob = clean_mobile(mob)
    clash = db.scalar(select(m.Player.id).where(m.Player.team_id == p.team_id, m.Player.id != p.id,
                                                func.lower(m.Player.player_name) == name.lower()))
    if clash:
        raise LedgerError(f"{name} already exists in this team.")
    before = {"name": p.player_name, "mob_no": p.mob_no}
    p.player_name, p.mob_no = name, mob
    log(db, actor, "player.edit", "player", p.id, p.team_id, {"before": before, "after": {"name": name, "mob_no": mob}})


def set_player_archived(db: Session, player_id: int, archived: bool, actor: str) -> None:
    p = db.get(m.Player, player_id)
    if p is None:
        raise LedgerError("Player not found.")
    p.status = "archived" if archived else "active"
    p.account.status = p.status
    log(db, actor, "player.archive" if archived else "player.restore", "player", p.id, p.team_id, {})


def delete_player(db: Session, player_id: int, actor: str) -> None:
    p = db.get(m.Player, player_id)
    if p is None:
        raise LedgerError("Player not found.")
    acct = p.account
    used = db.scalar(select(func.count()).select_from(m.TransactionAccount).where(m.TransactionAccount.account_id == acct.id))
    used += db.scalar(select(func.count()).select_from(m.Allocation).where(m.Allocation.account_id == acct.id))
    used += db.scalar(select(func.count()).select_from(m.Settlement).where(m.Settlement.account_id == acct.id))
    if used:
        raise LedgerError(f"{p.player_name} is part of the ledger and cannot be deleted. Archive the player instead.")
    name, team_id = p.player_name, p.team_id
    db.delete(acct)
    db.flush()
    db.delete(p)
    db.flush()
    log(db, actor, "player.delete", "player", player_id, team_id, {"name": name})


def import_players_csv(db: Session, team_id: int, raw: bytes, actor: str) -> dict:
    if len(raw) > 1_000_000:
        raise LedgerError("CSV file is too large (1 MB max).")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise LedgerError("CSV must be UTF-8 encoded.")
    rows = list(csv.reader(io.StringIO(text)))
    if rows and rows[0] and rows[0][0].strip().lower() in ("player_name", "name", "player"):
        rows = rows[1:]
    if len(rows) > 1000:
        raise LedgerError("CSV has more than 1000 rows.")
    added, skipped, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):
        if not row or not any(c.strip() for c in row):
            continue
        name = row[0]
        mob = row[1] if len(row) > 1 else None
        try:
            with db.begin_nested():
                create_player(db, team_id, name, mob, actor)
            added += 1
        except LedgerError as e:
            if "already exists" in str(e):
                skipped += 1
            else:
                errors.append(f"Row {i}: {e}")
    log(db, actor, "player.import", "team", team_id, team_id, {"added": added, "skipped": skipped, "errors": len(errors)})
    return {"added": added, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------- categories

def create_category(db: Session, name: str, kind: str, actor: str) -> m.Category:
    if kind not in ("income", "expense"):
        raise LedgerError("Choose income or expense.")
    name = _clean_name(name, "Category name", 60)
    if db.scalar(select(m.Category.id).where(m.Category.kind == kind, func.lower(m.Category.name) == name.lower())):
        raise LedgerError(f"'{name}' already exists under {kind}.")
    top = db.scalar(select(func.coalesce(func.max(m.Category.sort_order), 0)).where(m.Category.kind == kind))
    c = m.Category(name=name, kind=kind, is_other=(name.lower() == "other"), sort_order=top + 1)
    db.add(c)
    db.flush()
    log(db, actor, "category.create", "category", c.id, None, {"name": name, "kind": kind})
    return c


def rename_category(db: Session, cat_id: int, name: str, actor: str) -> None:
    c = db.get(m.Category, cat_id)
    if c is None:
        raise LedgerError("Category not found.")
    name = _clean_name(name, "Category name", 60)
    clash = db.scalar(select(m.Category.id).where(m.Category.kind == c.kind, m.Category.id != c.id,
                                                  func.lower(m.Category.name) == name.lower()))
    if clash:
        raise LedgerError(f"'{name}' already exists under {c.kind}.")
    old, c.name = c.name, name
    log(db, actor, "category.rename", "category", c.id, None, {"from": old, "to": name})


def set_category_archived(db: Session, cat_id: int, archived: bool, actor: str) -> None:
    c = db.get(m.Category, cat_id)
    if c is None:
        raise LedgerError("Category not found.")
    c.status = "archived" if archived else "active"
    log(db, actor, "category.archive" if archived else "category.restore", "category", c.id, None, {"name": c.name})
