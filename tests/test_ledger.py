import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import models as m
from app.services import ledger, masters
from app.services.ledger import LedgerError, TxnInput

from .conftest import NAMES, account_of, cat, expense

D = Decimal


def test_per_party_charge_rounding():
    assert ledger.per_party_charge(D("1000"), 6, D(5)) == D("170.00")
    assert ledger.per_party_charge(D("1000"), 6, D(3)) == D("168.00")
    assert ledger.per_party_charge(D("1000"), 4, D(5)) == D("250.00")      # exact, no bump
    assert ledger.per_party_charge(D("1000"), 1, D(5)) == D("1000.00")     # single party is exact
    assert ledger.per_party_charge(D("100.50"), 3, D(1)) == D("34.00")


def test_team_creates_separate_accounts(db):
    a = masters.create_team(db, "Team A", "t")
    b = masters.create_team(db, "Team B", "t")
    db.commit()
    aa, bb = ledger.get_team_account(db, a.id), ledger.get_team_account(db, b.id)
    assert aa.id != bb.id and aa.team_id == a.id and bb.team_id == b.id
    with pytest.raises(LedgerError):
        masters.create_team(db, "team a", "t")


def test_allocation_and_surplus_step_5(db, team):
    t = expense(db, team, 1000, "Akshay", NAMES)
    assert [a.allocated_amount for a in t.allocations] == [D("170.00")] * 6
    assert t.surplus_amount == D("20.00")
    assert ledger.team_summary(db, team.id)["surplus"] == D("20.00")
    # no artificial player balance for the rounding difference: total owed is 1020, not more
    rows = ledger.player_balances(db, team.id)
    assert sum(r["owed"] for r in rows) == D("1020.00")


def test_rounding_step_is_a_setting_and_example_with_3(db, team):
    ledger.set_setting(db, "rounding_step", "3")
    t = expense(db, team, 1000, "team", NAMES)
    assert {a.allocated_amount for a in t.allocations} == {D("168.00")}
    assert t.surplus_amount == D("8.00")


def test_net_outstanding_is_owed_minus_paid(db, team):
    expense(db, team, 1000, "Akshay", NAMES)
    by = {r["player"].player_name: r for r in ledger.player_balances(db, team.id)}
    assert by["Akshay"]["owed"] == D("170.00") and by["Akshay"]["paid"] == D("1000.00")
    assert by["Akshay"]["net"] == D("-830.00")
    assert by["Bala"]["net"] == D("170.00")
    order = [r["player"].player_name for r in ledger.player_balances(db, team.id)]
    assert order[-1] == "Akshay"  # lowest net last


def test_reimbursement_is_full_once_and_a_transfer(db, team):
    t = expense(db, team, 1000, "Akshay", NAMES)
    ledger.reimburse(db, t.id, "test")
    db.commit()
    transfers = db.scalars(select(m.Transaction).where(m.Transaction.type == "transfer")).all()
    assert len(transfers) == 1 and transfers[0].amount == D("1000.00")
    assert db.get(m.Transaction, t.id).type == "expense"
    with pytest.raises(LedgerError):
        ledger.reimburse(db, t.id, "test")
    db.rollback()
    assert len(db.scalars(select(m.Transaction).where(m.Transaction.type == "transfer")).all()) == 1
    by = {r["player"].player_name: r for r in ledger.player_balances(db, team.id)}
    assert by["Akshay"]["net"] == D("170.00")
    s = ledger.team_summary(db, team.id)
    assert s["balance"] == D("-1000.00")  # team paid the player out of its account


def test_reimburse_requires_player_payer(db, team):
    t = expense(db, team, 500, "team", NAMES[:2])
    with pytest.raises(LedgerError):
        ledger.reimburse(db, t.id, "test")


def test_collection_full_or_none_and_no_duplicates(db, team):
    t = expense(db, team, 1000, "team", NAMES)
    a = next(x for x in t.allocations if x.account_id == account_of(db, team.id, "Bala").id)
    ledger.collect(db, a.id, "test")
    db.commit()
    by = {r["player"].player_name: r for r in ledger.player_balances(db, team.id)}
    assert by["Bala"]["paid"] == D("170.00") and by["Bala"]["net"] == D("0.00")
    assert by["Chetan"]["net"] == D("170.00")
    with pytest.raises(LedgerError):
        ledger.collect(db, a.id, "test")
    db.rollback()
    assert ledger.team_summary(db, team.id)["balance"] == D("-830.00")


def test_database_blocks_duplicate_active_settlement(db, team):
    t = expense(db, team, 1000, "Akshay", NAMES)
    s = ledger.reimburse(db, t.id, "test")
    db.commit()
    from sqlalchemy.exc import IntegrityError
    db.add(m.Settlement(kind="reimbursement", transaction_id=t.id, account_id=s.account_id, amount=t.amount, status="active"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_void_cascades_and_recalculates(db, team):
    t = expense(db, team, 1000, "Akshay", NAMES)
    ledger.reimburse(db, t.id, "test")
    ledger.collect_all(db, t.id, "test")
    db.commit()
    ledger.void_transaction(db, t.id, "test", "wrong amount")
    db.commit()
    db.expire_all()
    assert db.get(m.Transaction, t.id).status == "voided"
    transfers = db.scalars(select(m.Transaction).where(m.Transaction.type == "transfer")).all()
    assert transfers and all(x.status == "reversed" for x in transfers)
    assert all(r["net"] == 0 for r in ledger.player_balances(db, team.id))
    s = ledger.team_summary(db, team.id)
    assert s["total_out"] == 0 and s["balance"] == 0 and s["surplus"] == 0
    with pytest.raises(LedgerError):
        ledger.void_transaction(db, t.id, "test")
    db.rollback()
    logged = {a.action for a in db.scalars(select(m.AuditLog)).all()}
    assert {"transaction.create", "transaction.void", "settlement.reverse"} <= logged


def test_reversing_a_settlement_reopens_it(db, team):
    t = expense(db, team, 1000, "team", NAMES)
    a = t.allocations[0]
    s = ledger.collect(db, a.id, "test")
    db.commit()
    ledger.void_transaction(db, s.settlement_transaction_id, "test")  # voiding the transfer reverses the settlement
    db.commit()
    db.refresh(a)
    assert a.settlement_status == 0 and a.settled_transaction_id is None
    ledger.collect(db, a.id, "test")  # can be collected again
    db.commit()


def test_edit_rules(db, team):
    t = expense(db, team, 1000, "Akshay", NAMES)
    d = TxnInput(team_id=team.id, date=dt.date(2026, 9, 2), type="expense", amount=D("600"),
                 category_id=cat(db, "Balls", "expense").id, paid_by=account_of(db, team.id, "Akshay").id,
                 charged_to=[account_of(db, team.id, n).id for n in NAMES[:3]])
    ledger.update_transaction(db, t.id, d, "test")
    db.commit()
    db.refresh(t)
    assert t.amount == D("600.00") and len(t.allocations) == 3 and t.surplus_amount == D("0.00")
    ledger.reimburse(db, t.id, "test")
    db.commit()
    with pytest.raises(LedgerError):
        ledger.update_transaction(db, t.id, d, "test")
    db.rollback()


def test_partial_and_bad_amounts_rejected(db, team):
    base = dict(team_id=team.id, date=dt.date(2026, 9, 1), type="expense", category_id=cat(db, "Balls", "expense").id,
                paid_by=account_of(db, team.id, "Akshay").id, charged_to=[account_of(db, team.id, "Bala").id])
    for bad in ("0", "-5", "10.555", "99999999"):
        with pytest.raises(LedgerError):
            ledger.create_transaction(db, TxnInput(amount=D(bad), **base), "t")
        db.rollback()


def test_other_category_needs_description(db, team):
    base = dict(team_id=team.id, date=dt.date(2026, 9, 1), type="expense", amount=D("100"),
                category_id=cat(db, "Other", "expense").id, paid_by=account_of(db, team.id, "Akshay").id,
                charged_to=[account_of(db, team.id, "Bala").id])
    with pytest.raises(LedgerError):
        ledger.create_transaction(db, TxnInput(**base), "t")
    db.rollback()
    ledger.create_transaction(db, TxnInput(item_description="Umpire fee", **base), "t")


def test_income_and_transfer_and_team_balance(db, team):
    masters.set_opening_balance(db, team.id, D("500"), "t")
    ta = ledger.get_team_account(db, team.id)
    bala = account_of(db, team.id, "Bala")
    ledger.create_transaction(db, TxnInput(team_id=team.id, date=dt.date(2026, 9, 1), type="income", amount=D("1000"),
                                           category_id=cat(db, "Sponsorship", "income").id), "t")
    ledger.create_transaction(db, TxnInput(team_id=team.id, date=dt.date(2026, 9, 1), type="income", amount=D("200"),
                                           category_id=cat(db, "Team Contribution", "income").id, paid_by=bala.id), "t")
    ledger.create_transaction(db, TxnInput(team_id=team.id, date=dt.date(2026, 9, 2), type="transfer", amount=D("300"),
                                           account_in=bala.id, account_out=ta.id), "t")
    expense(db, team, 400, "team", ["team"], category="Nets")
    s = ledger.team_summary(db, team.id)
    assert s["total_in"] == 1200 and s["total_out"] == 400
    assert s["balance"] == D("500") + 1200 - 300 - 400
    by = {r["player"].player_name: r for r in ledger.player_balances(db, team.id)}
    assert by["Bala"]["paid"] == D("200") - D("300") and by["Bala"]["net"] == D("100")  # owed nothing, received 300 > paid 200


def test_transfer_validation(db, team):
    ta = ledger.get_team_account(db, team.id)
    bala = account_of(db, team.id, "Bala")
    base = dict(team_id=team.id, date=dt.date(2026, 9, 1), type="transfer", amount=D("10"))
    for kw in ({"account_in": bala.id, "account_out": bala.id}, {"account_in": bala.id}, {}):
        with pytest.raises(LedgerError):
            ledger.create_transaction(db, TxnInput(**base, **kw), "t")
        db.rollback()


def test_team_isolation_enforced_in_service(db, team):
    other = masters.create_team(db, "Team B", "t")
    masters.create_player(db, other.id, "Zed", None, "t")
    db.commit()
    zed = account_of(db, other.id, "Zed")
    with pytest.raises(LedgerError):
        ledger.create_transaction(db, TxnInput(
            team_id=team.id, date=dt.date(2026, 9, 1), type="expense", amount=D("100"),
            category_id=cat(db, "Balls", "expense").id, paid_by=zed.id, charged_to=[zed.id]), "t")
    db.rollback()
    expense(db, team, 100, "Akshay", ["Bala"])
    assert ledger.team_summary(db, other.id)["total_out"] == 0
    assert ledger.player_balances(db, other.id)[0]["net"] == 0


def test_player_history_running_balance(db, team):
    t = expense(db, team, 1000, "Akshay", NAMES)
    ledger.reimburse(db, t.id, "t")
    db.commit()
    p = next(r["player"] for r in ledger.player_balances(db, team.id) if r["player"].player_name == "Akshay")
    events, net = ledger.player_history(db, p)
    assert [e["role"] for e in events] == ["Owed", "Paid", "Reimbursed"]
    assert net == D("170.00") == events[-1]["running"]


def test_delete_player_rules(db, team):
    t = expense(db, team, 100, "Akshay", ["Bala"])
    bala = db.scalar(select(m.Player).where(m.Player.player_name == "Bala"))
    with pytest.raises(LedgerError):
        masters.delete_player(db, bala.id, "t")
    db.rollback()
    esha = db.scalar(select(m.Player).where(m.Player.player_name == "Esha"))
    masters.delete_player(db, esha.id, "t")
    db.commit()


def test_csv_import(db, team):
    raw = b"player_name,mob_no\nNew One,98765 43210\nakshay,\n,\nBad Num,abc\n"
    res = masters.import_players_csv(db, team.id, raw, "t")
    db.commit()
    assert res["added"] == 1 and res["skipped"] == 1 and len(res["errors"]) == 1


def test_reset_all_and_since_keeps_audit(db, team):
    t1 = expense(db, team, 1000, "Akshay", NAMES)
    ledger.reimburse(db, t1.id, "t")
    db.commit()
    audit_before = db.scalar(select(m.AuditLog.id).order_by(m.AuditLog.id.desc()))
    ledger.reset_data(db, "t", since=None)
    db.commit()
    assert db.scalars(select(m.Transaction)).all() == []
    assert db.scalars(select(m.Settlement)).all() == []
    assert db.scalar(select(m.AuditLog.id).order_by(m.AuditLog.id.desc())) > audit_before
    assert len(db.scalars(select(m.Team)).all()) == 1 and len(db.scalars(select(m.Player)).all()) == 6


def test_reset_since_reopens_parent_when_only_settlement_removed(db, team):
    t = expense(db, team, 1000, "team", NAMES)
    cutoff = m.utcnow() + dt.timedelta(seconds=1)
    import time
    time.sleep(1.2)
    a = t.allocations[0]
    ledger.collect(db, a.id, "t")
    db.commit()
    ledger.reset_data(db, "t", since=cutoff)
    db.commit()
    db.expire_all()
    assert db.get(m.Transaction, t.id) is not None
    assert db.get(m.Allocation, a.id).settlement_status == 0
    assert db.scalars(select(m.Settlement)).all() == []
