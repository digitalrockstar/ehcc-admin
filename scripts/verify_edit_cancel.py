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
    cancel_match, ConfirmationRequired, InvalidEdit,
)

Base.metadata.create_all(bind=engine)
db = SessionLocal()

team = models.Team(name="T", starting_balance=1000)
db.add(team); db.commit(); db.refresh(team)
players = [models.Player(team_id=team.id, name=f"P{i}") for i in range(6)]
db.add_all(players); db.commit()
for p in players: db.refresh(p)
pids = [p.id for p in players[:4]]  # start with 4 players

match = create_match(db, team.id, date(2026, 9, 1), 400, 0, pids)  # fee = 100 each

# No payments yet -> amount edit applies without confirmation, same player set
apply_match_edit(db, match.id, 800, 0, pids, confirmed=False)
db.refresh(match)
assert match.participants[0].fee_amount == 200, "free recalculation failed"

# Add a 5th player while no one has paid -> no confirmation needed
new_pids = pids + [players[4].id]
apply_match_edit(db, match.id, 800, 0, new_pids, confirmed=False)
db.refresh(match)
assert len(match.participants) == 5
assert all(p.fee_amount == 160 for p in match.participants), "fee not recalculated for 5 players (800/5=160)"

# Now one player pays
mark_match_fee_paid(db, match.participants[0].id, 160)

# Try removing an unpaid player without confirm -> must raise (has_payments True)
paid_pid_marker = match.participants[0].player_id
remaining_pids = [p.player_id for p in match.participants if p.player_id != paid_pid_marker][:-1] + [paid_pid_marker]
try:
    apply_match_edit(db, match.id, 400, 0, remaining_pids, confirmed=False)
    raise SystemExit("FAILED: should have required confirmation")
except ConfirmationRequired as e:
    assert e.preview["has_payments"] is True

# Try removing the PAID player -> must hard-block regardless of confirm
pids_without_paid = [p.id for p in match.participants if p.player_id != match.participants[0].player_id]
try:
    apply_match_edit(db, match.id, 400, 0, pids_without_paid, confirmed=True)
    raise SystemExit("FAILED: removing a paid player should be blocked")
except InvalidEdit:
    pass

# Confirm a valid edit (remove an unpaid player, add none) -> paid stays untouched
paid_participant_pid = match.participants[0].player_id
unpaid_pids = [p.player_id for p in match.participants if p.player_id != paid_participant_pid]
kept_pids = [paid_participant_pid] + unpaid_pids[:-1]  # drop one unpaid player
apply_match_edit(db, match.id, 400, 0, kept_pids, confirmed=True)
db.refresh(match)
assert len(match.participants) == 4
paid = [p for p in match.participants if p.status == models.PaymentStatus.paid][0]
due = [p for p in match.participants if p.status == models.PaymentStatus.due]
assert paid.fee_amount == 160, "paid participant's fee was overwritten!"
assert all(p.fee_amount == 100 for p in due), f"unpaid participants not recalculated: {[p.fee_amount for p in due]}"

# Cancel without confirm on a match with payments -> must raise
try:
    cancel_match(db, match.id, confirmed=False)
    raise SystemExit("FAILED: cancel should have required confirmation")
except ConfirmationRequired:
    pass
cancel_match(db, match.id, confirmed=True)
db.refresh(match)
assert match.status == models.MatchStatus.cancelled

print("MATCH EDIT (incl. add/remove players) + CANCEL CONFIRMATION FLOW: ALL CHECKS PASSED")
db.close()
os.remove("verify2.db")
