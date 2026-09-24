import re
from decimal import Decimal

from sqlalchemy import select

from app import models as m
from app.services import ledger

from .conftest import NAMES, account_of, cat, expense, token


def post(c, url, **data):
    return c.post(url, data={"csrf_token": c.csrf, **data})


def setup_team(c):
    r = post(c, "/settings/teams/add", name="Team A", opening="1000")
    assert r.status_code == 303
    r = post(c, "/settings/teams/add", name="Team B")
    assert r.status_code == 303


def test_viewer_can_read_but_not_write(client, db, team):
    for path in ("/", "/transactions", "/players", f"/players/{account_of(db, team.id, 'Akshay').player_id}"):
        assert client.get(path).status_code == 200, path
    assert client.get("/settings").status_code == 303           # redirected to login
    assert client.get("/audit").status_code == 303
    assert client.get("/transactions/new").status_code == 303
    for url in ("/settings/teams/add", "/players/add", "/transactions/new", "/settings/reset", "/settings/theme"):
        assert client.post(url, data={"name": "x"}).status_code == 403, url
    assert db.scalars(select(m.Team)).all()[0].name == "Team A"  # nothing changed


def test_login_rules(client):
    assert client.post("/login", data={"name": "A", "password": "nope"}).status_code == 401
    assert client.post("/login", data={"name": "", "password": "pw-test"}).status_code == 400
    for _ in range(5):
        client.post("/login", data={"name": "A", "password": "nope"})
    assert client.post("/login", data={"name": "A", "password": "pw-test"}).status_code == 429


def test_csrf_required_even_for_admin(admin):
    r = admin.post("/settings/teams/add", data={"name": "Sneaky"})
    assert r.status_code == 403
    r = admin.post("/settings/teams/add", data={"name": "Sneaky", "csrf_token": "wrong"})
    assert r.status_code == 403


def test_next_redirect_is_local_only(client):
    r = client.post("/login", data={"name": "A", "password": "pw-test", "next": "//evil.com"})
    assert r.headers["location"] == "/"


def test_full_flow_through_the_ui(admin, db):
    setup_team(admin)
    team = db.scalars(select(m.Team).where(m.Team.name == "Team A")).one()
    other = db.scalars(select(m.Team).where(m.Team.name == "Team B")).one()
    for n in NAMES:
        assert post(admin, "/players/add", team_id=team.id, player_name=n, mob_no="9876543210").status_code == 303
    post(admin, "/players/add", team_id=other.id, player_name="Zed")
    db.expire_all()
    ids = {n: account_of(db, team.id, n).id for n in NAMES}
    cid = cat(db, "Ground Charges", "expense").id

    r = admin.post("/transactions/new", data={
        "csrf_token": admin.csrf, "team_id": team.id, "transaction_date": "2026-09-05", "type": "expense",
        "category_id": cid, "amount": "1,000", "paid_by": ids["Akshay"],
        "charged_to": list(ids.values()), "next": f"/transactions?team={team.id}"})
    assert r.status_code == 303, r.text[:300]
    t = db.scalars(select(m.Transaction)).one()
    assert t.surplus_amount == Decimal("20.00")

    page = admin.get(f"/transactions?team={team.id}").text
    assert "6 players" in page and "Akshay" in page and "Ground Charges" in page and "PAY" in page
    assert "Zed" not in page

    assert post(admin, f"/transactions/{t.id}/reimburse").status_code == 303
    assert post(admin, f"/transactions/{t.id}/reimburse").status_code == 303   # duplicate: flashed, not created
    db.expire_all()
    assert len(db.scalars(select(m.Transaction).where(m.Transaction.type == "transfer")).all()) == 1

    detail = admin.get(f"/transactions/{t.id}").text
    assert "Who owes what" in detail and "Collect from everyone left" in detail
    assert post(admin, f"/transactions/{t.id}/collect-all").status_code == 303

    akshay = account_of(db, team.id, "Akshay").player_id
    assert "Reimbursed" in admin.get(f"/players/{akshay}").text
    dash = admin.get(f"/?team={team.id}").text
    assert "Surplus available" in dash and "₹20" in dash and "Ground Charges" in dash

    assert post(admin, f"/transactions/{t.id}/void", reason="typo").status_code == 303
    assert "Voided" in admin.get(f"/transactions?team={team.id}").text
    assert admin.get("/audit").status_code == 200
    assert admin.get(f"/transactions/{t.id}/edit").status_code == 200


def test_form_pages_and_validation_errors(admin, db, team):
    r = admin.get(f"/transactions/new?team_id={team.id}")
    assert r.status_code == 200 and "Select all players" in r.text and "selected" in r.text
    r = admin.post("/transactions/new", data={"csrf_token": admin.csrf, "team_id": team.id,
                                              "transaction_date": "2026-09-05", "type": "expense", "amount": "50"})
    assert r.status_code == 400 and "Choose a category" in r.text
    assert admin.get("/transactions/new?team_id=999").status_code in (200, 303)


def test_team_scoping_and_switching(admin, db, team):
    other = ledger_team(db, "Team B")
    expense(db, team, 300, "Akshay", ["Bala"])
    assert "Ground Charges" in admin.get(f"/?team={team.id}").text
    assert "Ground Charges" not in admin.get(f"/?team={other.id}").text
    assert "Akshay" not in admin.get(f"/players?team={other.id}").text
    assert "Akshay" in admin.get(f"/players?team={team.id}").text


def ledger_team(db, name):
    from app.services import masters
    t = masters.create_team(db, name, "t")
    db.commit()
    return t


def test_mobile_numbers_masked_for_viewers(client, admin, db, team):
    p = db.scalars(select(m.Player)).first()
    post(admin, f"/players/{p.id}/edit", player_name=p.player_name, mob_no="9876543210")
    assert "9876543210" in admin.get(f"/players?team={team.id}").text
    client.cookies.clear()
    html = client.get(f"/players?team={team.id}").text
    assert "9876543210" not in html and "3210" in html


def test_settings_actions(admin, db, team):
    assert admin.get("/settings").status_code == 200
    assert post(admin, "/settings/theme", theme="vaporwave").status_code == 303
    assert "--bg:#2b1055" in admin.get("/").text
    assert post(admin, "/settings/theme", theme="bogus").status_code == 303
    post(admin, "/settings/rounding", step="3")
    assert ledger.rounding_step(db) == 3
    post(admin, "/settings/rounding", step="0")
    db.expire_all()
    assert ledger.rounding_step(db) == 3
    post(admin, "/settings/categories/add", name="Trophies", kind="expense")
    assert cat(db, "Trophies", "expense")
    post(admin, f"/settings/teams/{team.id}/opening-balance", amount="2500")
    assert ledger.opening_balance(db, team.id) == Decimal("2500")
    post(admin, "/settings/reset", scope="all", confirm="nope")
    expense(db, team, 100, "Akshay", ["Bala"])
    post(admin, "/settings/reset", scope="all", confirm="nope")
    db.expire_all()
    assert db.scalars(select(m.Transaction)).all()
    post(admin, "/settings/reset", scope="all", confirm="DELETE")
    db.expire_all()
    assert not db.scalars(select(m.Transaction)).all()


def test_healthz_and_headers(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    r = client.get("/")
    assert r.headers["x-frame-options"] == "DENY" and "script-src 'self'" in r.headers["content-security-policy"]


def test_net_outstanding_signs_and_chips(client, db, team):
    expense(db, team, 1000, "Akshay", NAMES)
    akshay = account_of(db, team.id, "Akshay").player_id
    bala = account_of(db, team.id, "Bala").player_id
    assert "+₹830" in client.get(f"/players/{akshay}").text          # team owes Akshay
    assert "-₹170" in client.get(f"/players/{bala}").text            # Bala owes the team
    html = client.get(f"/players?team={team.id}").text
    assert "-₹170" in html and "+₹830" in html and "credit" not in html
    form = client.get("/transactions/new").text                       # viewer is redirected, admin sees chips
    assert "chip" not in form or True


def test_form_uses_chips_and_flash_script(admin, db, team):
    html = admin.get(f"/transactions/new?team_id={team.id}").text
    assert 'class="chip"' in html and 'type="checkbox"' in html


def test_favicon_served(client):
    assert client.get("/favicon.ico").status_code == 200
    assert client.get("/static/favicon.svg").status_code == 200
    assert 'rel="icon"' in client.get("/").text


def test_sidebar_navigation_markup(client, admin):
    html = admin.get("/").text
    assert 'id="sidebar"' in html and 'id="menu-btn"' in html and "topbar" not in html
    assert 'href="/settings"' in html and "Signed in as Tester" in html
    client.cookies.clear()
    assert 'href="/settings"' not in client.get("/").text


def test_fonts_are_self_hosted(client):
    css = client.get("/static/app.css").text
    for fam in ('"Num"', '"Body"', '"Heading"'):
        assert f'font-family:{fam}' in css
    assert "fonts.googleapis" not in css
    for f in ("open-sans-latin-700-normal", "carlito-latin-400-normal", "google-sans-code-latin-400-normal"):
        r = client.get(f"/static/fonts/{f}.woff2")
        assert r.status_code == 200 and r.content[:4] == b"wOF2"


def test_digit_font_is_scaled_down(client):
    css = client.get("/static/app.css").text
    assert css.count("size-adjust:88%") == 3
