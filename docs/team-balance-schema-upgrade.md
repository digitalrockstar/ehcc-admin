# Team-balance schema upgrade

This change does not add a table or column. It expands the existing `settlements.kind`
CHECK constraint so a rounded collection adjustment can be recorded as a reversible
`team_balance` settlement. Existing data is retained.

## Output 1 — SQL for Neon

Run `docs/sql/0003_team_balance_settlement.sql` against the Neon database.

## Output 2 — Python script

Run:

```bash
DATABASE_URL='your-Neon-SQLAlchemy-URL' python scripts/upgrade_team_balance_schema.py
```

The script is idempotent and only supports PostgreSQL. Prefer the normal Alembic migration
for deployment.

## Output 3 — application schema setup / migration

The Alembic migration `0003_team_balance_settlement.py` updates the constraint with a
batch table alteration compatible with PostgreSQL and SQLite. Apply with:

```bash
alembic upgrade head
```

There are no new columns to conditionally add and no new table required for this change.
The existing reset actions remain available for clearing today's test transactions.
