"""Idempotent schema upgrade for EHCC Admin on Neon PostgreSQL.

Usage:
    DATABASE_URL='postgresql+psycopg://...' python scripts/upgrade_team_balance_schema.py

Prefer `alembic upgrade head` for normal deployments. This script creates missing model
tables, adds the new movement column if missing, and updates settlement indexes/constraint.
"""
import os
from sqlalchemy import create_engine, inspect, text
from app.models import Base

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("Set DATABASE_URL to the Neon SQLAlchemy connection string.")
engine = create_engine(url, pool_pre_ping=True)
if engine.dialect.name != "postgresql":
    raise SystemExit("This standalone schema script supports PostgreSQL only; use Alembic for SQLite.")

# Creates only absent tables. It does not delete or rewrite existing ledger rows.
Base.metadata.create_all(engine)
with engine.begin() as conn:
    cols = {col["name"] for col in inspect(conn).get_columns("player_credit_movements")}
    if "reversed_at" not in cols:
        conn.execute(text("ALTER TABLE player_credit_movements ADD COLUMN reversed_at TIMESTAMPTZ"))
    constraint = conn.execute(text("""
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_settlements_kind' AND conrelid = to_regclass('public.settlements')
    """)).scalar()
    if constraint:
        conn.execute(text("ALTER TABLE public.settlements DROP CONSTRAINT ck_settlements_kind"))
    conn.execute(text("""
        ALTER TABLE public.settlements ADD CONSTRAINT ck_settlements_kind
        CHECK (kind IN ('reimbursement', 'collection', 'team_balance'))
    """))
    conn.execute(text("DROP INDEX IF EXISTS public.uq_active_settlement"))
    conn.execute(text("""CREATE UNIQUE INDEX IF NOT EXISTS uq_active_reimbursement
        ON public.settlements(transaction_id, account_id)
        WHERE status='active' AND kind='reimbursement'"""))
    conn.execute(text("""CREATE UNIQUE INDEX IF NOT EXISTS uq_active_team_balance
        ON public.settlements(transaction_id, kind)
        WHERE status='active' AND kind='team_balance'"""))
print("Schema updated: player credits, repeat collections, and team-balance settlements are ready.")
