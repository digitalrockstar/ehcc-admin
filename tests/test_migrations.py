import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_and_audit_is_append_only():
    path = Path(tempfile.mkdtemp()) / "mig.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}"}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(path)
    tables = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
    assert {"teams", "players", "categories", "accounts", "transactions", "transaction_accounts", "allocations",
            "settlements", "opening_balances", "audit_log", "app_settings"} <= tables
    con.execute("insert into audit_log(at, actor, action, entity_type) values ('2026-01-01','a','b','c')")
    for stmt in ("update audit_log set actor='x'", "delete from audit_log"):
        try:
            con.execute(stmt)
            raise AssertionError("audit_log should be append-only")
        except sqlite3.DatabaseError as e:
            assert "append-only" in str(e)
