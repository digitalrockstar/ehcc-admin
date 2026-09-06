import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "sqlite:///./verify3.db"
if os.path.exists("verify3.db"):
    os.remove("verify3.db")

from datetime import date, timedelta
from app.database import Base, engine, SessionLocal
from app import models
from app.services.player_service import get_players_sorted

Base.metadata.create_all(bind=engine)
db = SessionLocal()

team = models.Team(name="T", starting_balance=0)
db.add(team); db.commit(); db.refresh(team)

# Zed played 5 days ago, Amy played 20 days ago, Bob/Cara never played (no recent match)
zed = models.Player(team_id=team.id, name="Zed")
amy = models.Player(team_id=team.id, name="Amy")
bob = models.Player(team_id=team.id, name="Bob")
cara = models.Player(team_id=team.id, name="Cara")
old_player = models.Player(team_id=team.id, name="Ancient")  # played 40 days ago -> outside window
db.add_all([zed, amy, bob, cara, old_player]); db.commit()
for p in [zed, amy, bob, cara, old_player]: db.refresh(p)

def make_match(days_ago, players):
    m = models.Match(team_id=team.id, match_date=date.today() - timedelta(days=days_ago), ground_fees=100)
    db.add(m); db.flush()
    for p in players:
        db.add(models.MatchParticipant(match_id=m.id, player_id=p.id, fee_amount=50))
    db.commit()

make_match(5, [zed])
make_match(20, [amy])
make_match(40, [old_player])

result = [p.name for p in get_players_sorted(db, team.id)]
print(result)
assert result == ["Zed", "Amy", "Ancient", "Bob", "Cara"], f"unexpected order: {result}"
print("PLAYER RECENCY SORT: PASSED")
db.close()
os.remove("verify3.db")
