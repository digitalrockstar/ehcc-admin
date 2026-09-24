# EHCC Expense Tracker

Team-wise cricket ledger: income, expenses, transfers, player balances, full reimbursements and collections, and rounding surplus. Built to the PRD v2 (one integrated MVP).

**Stack:** FastAPI, Jinja2 templates (no build step), SQLAlchemy 2, Alembic, PostgreSQL (Neon) in production, SQLite for quick local runs. Hosted on Render.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then export the variables, or set them inline
export ADMIN_PASSWORD=change-me SECRET_KEY=any-long-random-string
alembic upgrade head
uvicorn app.main:app --reload
```

Open http://localhost:8000, log in from the top bar with your name and the admin password, then create a team in Settings.

Tests: `pytest`. To run them against Postgres: `TEST_DATABASE_URL=postgresql://user:pass@localhost/ehcc_test pytest`.

## Deploy on Render with Neon

1. Create a Neon project and copy its connection string.
2. On Render, create a Blueprint from this repo (`render.yaml`).
3. Set `DATABASE_URL` (Neon string) and `ADMIN_PASSWORD`. `SECRET_KEY` is generated for you.
4. Deploy. The start command runs `alembic upgrade head` before starting the server.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Neon/Postgres URL. `postgres://` and `postgresql://` are both accepted. |
| `ADMIN_PASSWORD` | Shared admin password. Admin login is disabled if unset. |
| `SECRET_KEY` | Signs session cookies. Required in production. |
| `APP_ENV` | `production` turns on secure cookies. |
| `SHOW_MOBILE_TO_VIEWERS` | `1` shows full mobile numbers to view-only visitors. Default is masked. |

## How the rules are implemented

- **Access:** anyone can view; only a logged-in admin can change anything. Every mutating route checks the admin session and a CSRF token on the server. Admins enter their name at login, and it is stamped on the audit log.
- **Teams:** creating a team creates its own team account in the same transaction. All accounts in a transaction must belong to that transaction's team, enforced in the service layer.
- **Allocation:** `CEILING((amount / parties) / step) * step`, with `step` a setting (default ₹5, Settings > Allocation rounding). A single party is charged the exact amount. The difference is stored on the transaction as `surplus_amount`. No player balance is created for it.
- **Balances:** always derived from active transactions, never stored. Player net outstanding = owed minus paid, where paid = expenses and income the player fronted + transfers out of the player - transfers into the player. Team account balance = starting balance + income + transfers in - transfers out - expenses paid by the team account.
- **Settlement:** reimbursement (team account to player) and collection (player to team account) each create one full transfer, linked through the `settlements` table. A partial unique index allows one active settlement per expense, party and kind, so duplicates fail at the database. Both operations run inside a database transaction with row locks.
- **Void / reversal:** nothing in the ledger is hard-deleted by normal use. Voiding an expense reverses its linked settlements (status `reversed`) and reopens nothing else. Voiding a settlement transfer reverses just that settlement. Editing is blocked while a transaction has active settlements.
- **Audit:** `audit_log` is append-only, enforced by a database trigger on Postgres and SQLite.
- **Data reset:** deletes transactions, allocations and settlements (all, or those recorded at or after a chosen time). Teams, players, categories and starting balances stay. The audit log is kept and records the reset.
