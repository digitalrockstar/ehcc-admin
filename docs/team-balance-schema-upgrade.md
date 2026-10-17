# EHCC Admin ledger schema upgrade

The update adds player credit balances and an immutable movement history, allows multiple collection transfers against an edited allocation, and allows reversible `team_balance` settlement records. Existing transactions and settlement transfer rows are retained.

## Output 1 — SQL for Neon

Run `docs/sql/0004_player_credits.sql` in the Neon SQL editor. It uses `IF NOT EXISTS` for tables/indexes and adds the missing `reversed_at` column safely.

## Output 2 — Python script

Run from the repository root:

```bash
DATABASE_URL='your-Neon-SQLAlchemy-URL' python scripts/upgrade_team_balance_schema.py
```

This script is PostgreSQL-only. It creates absent tables and updates the constraint/indexes without deleting ledger rows.

## Output 3 — startup compatibility and Alembic migration

`app/db.py::ensure_schema_compatibility()` creates absent model tables and checks existing tables for missing columns, adding missing columns where possible. It runs during app startup. Alembic remains the source of truth for constraints and indexes.

For controlled deployments, run:

```bash
alembic upgrade head
```

The existing Settings reset options remain available. Use “delete today’s transactions” only after confirming the selected team/date scope; audit log entries are retained.