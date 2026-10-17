"""Idempotent schema upgrade for EHCC Admin on Neon PostgreSQL.

Usage:
    DATABASE_URL='postgresql+psycopg://...' python scripts/upgrade_team_balance_schema.py

Prefer `alembic upgrade head` for normal deployments. This script creates missing credit tables,
adds missing model columns, and updates settlement indexes/constraint.
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

inspector = inspect(engine)
if not inspector.has_table("teams") or not inspector.has_table("settlements"):
    raise SystemExit("Core schema is missing. Run `alembic upgrade head` first.")

# Create just the new tables, not the whole app schema, so this script does not pre-empt
# the initial Alembic migration on an empty database.
Base.metadata.tables["player_credits"].create(engine, checkfirst=True)
Base.metadata.tables["player_credit_movements"].create(engine, checkfirst=True)

# Add any missing model columns on existing tables. New required columns receive a safe
# database default so existing rows remain readable; constraints/indexes are handled below.
with engine.begin() as conn:
    for table in Base.metadata.sorted_tables:
        if not inspect(conn).has_table(table.name):
            continue
        existing = {col["name"] for col in inspect(conn).get_columns(table.name)}
        for column in table.columns:
            if column.name in existing or column.primary_key:
                continue
            col_type = column.type.compile(dialect=engine.dialect)
            default_sql = ""
            if not column.nullable:
                if column.server_default is not None:
                    default_sql = f" DEFAULT {column.server_default.arg}"
                elif column.default is not None and not callable(column.default.arg):
                    value = column.default.arg
                    literal = "'" + value.replace("'", "''") + "'" if isinstance(value, str) else (
                        "TRUE" if value is True else "FALSE" if value is False else str(value))
                    default_sql = f" DEFAULT {literal}"
                elif column.type.__class__.__name__ in ("DateTime", "Date"):
                    default_sql = " DEFAULT CURRENT_TIMESTAMP"
                elif column.type.__class__.__name__ == "String":
                    default_sql = " DEFAULT ''"
                elif column.type.__class__.__name__ == "Boolean":
                    default_sql = " DEFAULT FALSE"
                else:
                    default_sql = " DEFAULT 0"
            null_sql = " NULL" if column.nullable else " NOT NULL"
            conn.execute(text(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}{default_sql}{null_sql}'
            ))

with engine.begin() as conn:
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
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_player_credits_team_id ON public.player_credits(team_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_player_credits_account_id ON public.player_credits(account_id)"))
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_player_credit_source_account ON public.player_credits(source_transaction_id, account_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_player_credit_movements_credit_id ON public.player_credit_movements(credit_id)"))
print("Schema updated: player credits, repeat collections, and team-balance settlements are ready.")
