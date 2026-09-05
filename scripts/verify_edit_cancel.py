import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite:///./verify2.db"
if os.path.exists("verify2.db"):
    os.remove("verify2.db")

from datetime import date
from app.database import Base, engine, SessionLocal
from app import models
from app.services.match_service import (
    create_match, mark_match_fee_paid, preview_match_edit, apply_match_edit,
    cancel_match, ConfirmationRequired,
)

Base.metadata.create_all(bind=engine)
db = SessionLocal()

team = models.Team(name="T", starting_balance=1000)
db.add(team); db.commit(); db.refresh(team)
players = [models.Player(team_id=team.id, name=f"P{i}") for i in range(4)]
db.add_all(players); db.commit()
for p in players: db.refresh(p)
pids = [p.id for p in players]

match = create_match(db, team.id, date(2026, 9, 1), 400, 0, pids)  # fee = 100 each

# No payments yet -> edit should apply without confirmation
apply_match_edit(db, match.id, 800, 0, confirmed=False)
db.refresh(match)
assert match.participants[0].fee_amount == 200, "free recalculation failed"

# Now one player pays
mark_match_fee_paid(db, match.participants[0].id, 200)

# Edit again without confirm -> must raise
try:
    apply_match_edit(db, match.id, 400, 0, confirmed=False)
    raise SystemExit("FAILED: should have required confirmation")
except ConfirmationRequired as e:
    assert e.preview["has_payments"] is True
    assert e.preview["paid_count"] == 1

# Confirm -> paid participant untouched, others recalculated
apply_match_edit(db, match.id, 400, 0, confirmed=True)
db.refresh(match)
paid = [p for p in match.participants if p.status == models.PaymentStatus.paid][0]
due = [p for p in match.participants if p.status == models.PaymentStatus.due]
assert paid.fee_amount == 200, "paid participant's fee was overwritten!"
assert all(p.fee_amount == 100 for p in due), "unpaid participants not recalculated"

# Cancel without confirm on a match with payments -> must raise
try:
    cancel_match(db, match.id, confirmed=False)
    raise SystemExit("FAILED: cancel should have required confirmation")
except ConfirmationRequired:
    pass
cancel_match(db, match.id, confirmed=True)
db.refresh(match)
assert match.status == models.MatchStatus.cancelled

print("MATCH EDIT + CANCEL CONFIRMATION FLOW: ALL CHECKS PASSED")
db.close()
os.remove("verify2.db")
