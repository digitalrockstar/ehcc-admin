"""Core regression coverage for PRD v2. Run with: pytest -q
Uses a fresh in-memory-per-file sqlite db via conftest-free setup."""
import os
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app import models
from app.main import app, seed_categories


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_categories()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _team(client, name="Team A", bal="10000"):
    client.post("/settings/teams", data={"name": name, "starting_balance": bal})
    from app.database import SessionLocal
    db = SessionLocal()
    team = db.query(models.Team).filter_by(name=name).first()
    db.close()
    return team


def test_team_creation_creates_account(client):
    team = _team(client)
    from app.database import SessionLocal
    db = SessionLocal()
    acc = db.query(models.Account).filter_by(kind="team", team_id=team.id).first()
    assert acc is not None
    db.close()


def test_allocation_rounds_to_nearest_5_and_records_surplus(client):
    team = _team(client)
    client.post("/team-switch", data={"team_id": str(team.id)})
    for n in ["P1", "P2", "P3", "P4", "P5", "P6"]:
        client.post(f"/players?team_id={team.id}", data={"player_name": n, "mob_no": ""})

    from app.database import SessionLocal
    db = SessionLocal()
    players = db.query(models.Player).filter_by(team_id=team.id).all()
    tacc = db.query(models.Account).filter_by(kind="team", team_id=team.id).first()
    cat = db.query(models.Category).filter_by(type="expense", name="Balls").first()
    charged = [db.query(models.Account).filter_by(kind="player", player_id=p.id).first().id for p in players]
    db.close()

    form = {
        "team_id": str(team.id), "transaction_date": "2026-09-24", "type": "expense",
        "category_id": str(cat.id), "item_description": "", "amount": "1000",
        "payer_account_id": str(tacc.id),
        "charged_to": [str(c) for c in charged],
    }
    client.post("/transactions", data=form)

    db = SessionLocal()
    txn = db.query(models.Transaction).filter_by(team_id=team.id, type="expense").first()
    allocs = db.query(models.Allocation).filter_by(transaction_id=txn.id).all()
    assert all(float(a.allocated_amount) == 170 for a in allocs)
    assert float(txn.surplus_amount) == 20
    db.close()


def test_settlement_is_binary_and_not_duplicable(client):
    team = _team(client)
    client.post("/team-switch", data={"team_id": str(team.id)})
    client.post(f"/players?team_id={team.id}", data={"player_name": "P1", "mob_no": ""})

    from app.database import SessionLocal
    db = SessionLocal()
    p = db.query(models.Player).filter_by(team_id=team.id).first()
    p_acc = db.query(models.Account).filter_by(kind="player", player_id=p.id).first()
    tacc = db.query(models.Account).filter_by(kind="team", team_id=team.id).first()
    cat = db.query(models.Category).filter_by(type="expense", name="Balls").first()
    db.close()

    client.post("/transactions", data={
        "team_id": str(team.id), "transaction_date": "2026-09-24", "type": "expense",
        "category_id": str(cat.id), "item_description": "", "amount": "170",
        "payer_account_id": str(tacc.id), "charged_to": str(p_acc.id),
    })

    db = SessionLocal()
    alloc = db.query(models.Allocation).filter_by(account_id=p_acc.id).first()
    db.close()

    client.post(f"/allocations/{alloc.id}/settle")
    client.post(f"/allocations/{alloc.id}/settle")  # duplicate attempt

    db = SessionLocal()
    alloc = db.query(models.Allocation).get(alloc.id)
    transfers = db.query(models.Transaction).filter_by(type="transfer").count()
    assert alloc.settlement_status == 1
    assert transfers == 1
    db.close()


def test_team_data_is_isolated(client):
    team_a = _team(client, "Team A")
    team_b = _team(client, "Team B")
    client.post("/team-switch", data={"team_id": str(team_a.id)})
    client.post(f"/players?team_id={team_a.id}", data={"player_name": "OnlyInA", "mob_no": ""})

    client.post("/team-switch", data={"team_id": str(team_b.id)})
    r = client.get("/players")
    assert "OnlyInA" not in r.text


def test_void_cascades_and_balance_reverts(client):
    team = _team(client)
    client.post("/team-switch", data={"team_id": str(team.id)})
    client.post(f"/players?team_id={team.id}", data={"player_name": "P1", "mob_no": ""})

    from app.database import SessionLocal
    from app.services.ledger_service import team_balance
    db = SessionLocal()
    p = db.query(models.Player).filter_by(team_id=team.id).first()
    p_acc = db.query(models.Account).filter_by(kind="player", player_id=p.id).first()
    tacc = db.query(models.Account).filter_by(kind="team", team_id=team.id).first()
    cat = db.query(models.Category).filter_by(type="expense", name="Balls").first()
    db.close()

    client.post("/transactions", data={
        "team_id": str(team.id), "transaction_date": "2026-09-24", "type": "expense",
        "category_id": str(cat.id), "item_description": "", "amount": "500",
        "payer_account_id": str(tacc.id), "charged_to": str(p_acc.id),
    })
    db = SessionLocal()
    txn = db.query(models.Transaction).filter_by(team_id=team.id, type="expense").first()
    alloc = db.query(models.Allocation).filter_by(transaction_id=txn.id).first()
    db.close()

    client.post(f"/allocations/{alloc.id}/settle")

    db = SessionLocal()
    bal_before_void = team_balance(db, team)
    txn = db.query(models.Transaction).get(txn.id)
    from app.services import ledger_service as ledger
    ledger.void_transaction(db, txn, actor="test")
    db.commit()
    bal_after_void = team_balance(db, team)
    assert bal_after_void == team.starting_balance
    db.close()
