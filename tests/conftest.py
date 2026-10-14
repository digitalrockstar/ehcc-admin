import os
import re
import tempfile

_url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ.update(DATABASE_URL=_url, ADMIN_PASSWORD="pw-test", SECRET_KEY="test-secret", APP_ENV="development")

import datetime as dt  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod, models as m  # noqa: E402
from app.main import app  # noqa: E402
from app.security import _fails  # noqa: E402
from app.services import ledger, masters  # noqa: E402

NAMES = ("Akshay", "Bala", "Chetan", "Dev", "Esha", "Farhan")


@pytest.fixture(autouse=True)
def clean_db():
    import warnings
    warnings.filterwarnings("ignore", message=".*Decimal.*")
    m.Base.metadata.drop_all(dbmod.engine)
    m.Base.metadata.create_all(dbmod.engine)
    with dbmod.SessionLocal() as s:
        masters.ensure_defaults(s)
    _fails.clear()


@pytest.fixture
def db():
    with dbmod.SessionLocal() as s:
        yield s


@pytest.fixture
def team(db):
    t = masters.create_team(db, "Team A", "test")
    for n in NAMES:
        masters.create_player(db, t.id, n, None, "test")
    db.commit()
    return t


def account_of(db, team_id, name):
    from sqlalchemy import select
    p = db.scalar(select(m.Player).where(m.Player.team_id == team_id, m.Player.player_name == name))
    return p.account


def cat(db, name, kind):
    from sqlalchemy import select
    return db.scalar(select(m.Category).where(m.Category.name == name, m.Category.kind == kind))


def expense(db, team, amount, payer, charged, category="Ground Charges", day=None):
    team_acct = ledger.get_team_account(db, team.id)
    def resolve(x):
        return team_acct.id if x == "team" else account_of(db, team.id, x).id
    d = ledger.TxnInput(team_id=team.id, date=day or dt.date(2026, 9, 1), type="expense", amount=Decimal(str(amount)),
                        category_id=cat(db, category, "expense").id, paid_by=resolve(payer),
                        charged_to=[resolve(c) for c in charged])
    t = ledger.create_transaction(db, d, "test")
    db.commit()
    return t


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as c:
        yield c


def token(client) -> str:
    html = client.get("/").text
    m_ = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m_.group(1) if m_ else ""


@pytest.fixture
def admin(client):
    r = client.post("/login", data={"name": "Tester", "password": "pw-test", "next": "/"})
    assert r.status_code == 303
    client.csrf = token(client)
    return client
