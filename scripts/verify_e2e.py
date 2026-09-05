"""Runs the exact Section 45 acceptance scenario against the real service
layer + a throwaway sqlite DB, and asserts every checkpoint number."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite:///./verify.db"

from datetime import date
from app.database import Base, engine, SessionLocal
from app import models
from app.services.team_service import get_account_balance, get_dashboard_summary
from app.services.match_service import create_match, pay_match_expense_from_account, mark_match_fee_paid
from app.services.expense_service import (
    create_team_expense, allocate_expense_to_players, pay_expense_allocation, reimburse_player_for_expense,
)

if os.path.exists("verify.db"):
    os.remove("verify.db")
Base.metadata.create_all(bind=engine)
db = SessionLocal()

# Step 1
team = models.Team(name="EHCC", starting_balance=10000)
db.add(team); db.commit(); db.refresh(team)
assert get_account_balance(db, team.id) == 10000, "Step1 failed"

players = []
for i in range(10):
    p = models.Player(team_id=team.id, name=f"P{i}")
    db.add(p); players.append(p)
db.commit()
for p in players:
    db.refresh(p)
pids = [p.id for p in players]

# Step 2/3: match, 4000+500 expense, 10 players -> fee 450, pay from account
match = create_match(db, team.id, date(2026, 9, 1), 4000, 500, pids)
assert match.participants[0].fee_amount == 450, "Step2 fee failed"
pay_match_expense_from_account(db, match.id)
assert get_account_balance(db, team.id) == 5500, f"Step3 failed: {get_account_balance(db, team.id)}"

# Step 4: 8 players pay 450 each
for p in match.participants[:8]:
    mark_match_fee_paid(db, p.id, 450)
assert get_account_balance(db, team.id) == 9100, f"Step4 failed: {get_account_balance(db, team.id)}"

# Step 5: Akshay (players[0]) buys balls for 470, personally
akshay = players[0]
expense = create_team_expense(db, team.id, date(2026, 9, 2), "Cricket Balls", 470, "player", akshay.id)
assert get_account_balance(db, team.id) == 9100, "Step5 failed: account moved when it shouldn't"

# Step 6: allocate to 5 players -> 94 each
five = [players[i].id for i in range(5)]
allocate_expense_to_players(db, expense.id, five)
db.refresh(expense)
assert all(a.amount == 94 for a in expense.allocations), "Step6 allocation failed"
assert sum(a.amount for a in expense.allocations) == 470

# Step 7: 3 players pay their 94 share
for a in expense.allocations[:3]:
    pay_expense_allocation(db, a.id)
assert get_account_balance(db, team.id) == 9382, f"Step7 failed: {get_account_balance(db, team.id)}"

# Step 8: reimburse Akshay 470
reimburse_player_for_expense(db, expense.id)
final_balance = get_account_balance(db, team.id)
assert final_balance == 8912, f"Step8 failed: {final_balance}"

summary = get_dashboard_summary(db, team.id)
assert summary["players_owe_team"] == 1088, f"Total receivables failed: {summary['players_owe_team']}"
assert summary["team_owes_players"] == 0, f"Total payables failed: {summary['team_owes_players']}"

print("ALL SECTION 45 ACCEPTANCE CHECKPOINTS PASSED")
print(f"Final account: {final_balance} | Players owe: {summary['players_owe_team']} | Team owes: {summary['team_owes_players']}")

db.close()
os.remove("verify.db")
