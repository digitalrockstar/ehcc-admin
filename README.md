# EHCC Accounts

Multi-team financial ledger for cricket teams — income, expenses, transfers,
player receivables/payables, ₹5-rounded allocation, reimbursement/collection
(full or none, never partial), void/reversal with cascading settlement
reversal, and an audit log. Built against
`EHCC_Expense_Tracker_PRD_v2.md`.

This is a from-scratch rebuild of the app (previously built against the v1
PRD, single-team). The v1 PRD's concepts — ceiling-to-whole-rupee match fees,
a single team — are superseded by v2's multi-team, ₹5-rounded model.

## Stack

FastAPI + SQLAlchemy + Alembic, Jinja2 + HTMX + Tailwind (CDN) for the UI,
Postgres (Neon) in production, SQLite for local dev. The PRD's suggested
stack was React/Next.js + Node/TypeScript; this keeps the existing
FastAPI/Python/Render/Neon platform instead, since it's a straight platform
swap with no functional upside for a single-admin tool and a much bigger
migration cost. Everything else in the PRD (schema, rounding rule,
settlement, void/reversal, teams) is implemented as specified.

## Local development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # edit as needed; sqlite works out of the box
alembic upgrade head
uvicorn app.main:app --reload
```

Visit `http://localhost:8000`. Auth is skipped locally unless you set
`ADMIN_USERNAME`/`ADMIN_PASSWORD`.

## Tests

```bash
pytest tests/ -q
```

Covers: ₹5 allocation rounding + surplus (Section 9/25), binary settlement
and duplicate-settlement blocking (Section 10), team data isolation
(Section 3/25), and void cascading through linked settlements with balance
reverting correctly (Section 21).

## Migrations

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

## Deploying to Render + Neon

1. Create a Neon Postgres database, copy its connection string.
2. In Render, create a Blueprint from this repo (`render.yaml` is already set up).
3. Set `DATABASE_URL` to the Neon connection string.
4. Set `ADMIN_USERNAME` / `ADMIN_PASSWORD` (or let Render generate the password).
5. Deploy. Render runs `alembic upgrade head` automatically before boot.

## Data model

`teams` (each with one `accounts` row of kind `team`) · `players` (each with
one `accounts` row of kind `player`) · `categories` (income/expense) ·
`transactions` (income/expense/transfer, always team-scoped) · `allocations`
(per-player owed/payable amounts arising from an expense, with binary
`settlement_status`) · `audit_log`.

Balances are always derived from active transactions (starting balance +
income − expense + transfer in − transfer out), never stored as a mutable
field, per Section 19.

## Known gaps (documented, not hidden)

- Reports screen (Section 36 in the earlier v1 PRD) is not part of v2 and
  was dropped; v2's dashboard covers totals, category breakdown, top-5
  outstanding, and recent transactions instead.
- Multi-select "charged to" checkbox list on the transaction form doesn't
  paginate — fine for typical squad sizes, would want a search box for very
  large player lists.
- `created_at`-based data reset assumes naive UTC timestamps, matching how
  `created_at` is stored; no timezone conversion UI yet.
