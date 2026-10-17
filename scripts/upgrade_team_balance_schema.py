"""Idempotent Neon schema compatibility update.

Usage:
    DATABASE_URL='postgresql+psycopg://...' python scripts/upgrade_team_balance_schema.py

Prefer `alembic upgrade head` for normal deployments. This script is the standalone
alternative for the single CHECK-constraint change; it preserves rows.
"""
import os
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("Set DATABASE_URL to the Neon connection string.")

engine = create_engine(url, pool_pre_ping=True)
with engine.begin() as conn:
    if conn.dialect.name != "postgresql":
        raise SystemExit(f"This manual upgrade supports PostgreSQL only, got {conn.dialect.name!r}.")
    exists = conn.execute(text("""
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_settlements_kind'
          AND conrelid = to_regclass('public.settlements')
    """)).scalar()
    if exists:
        conn.execute(text("ALTER TABLE public.settlements DROP CONSTRAINT ck_settlements_kind"))
    conn.execute(text("""
        ALTER TABLE public.settlements
        ADD CONSTRAINT ck_settlements_kind
        CHECK (kind IN ('reimbursement', 'collection', 'team_balance'))
    """))
print("Schema updated: settlements.kind accepts team_balance.")
