# EHCC Expense Tracker

Team-wise cricket ledger: income, expenses, transfers, player balances, full reimbursements and collections, and team-balance rounding adjustment. Built to the PRD v2 (one integrated MVP).

**Stack:** FastAPI, Jinja2 templates (no build step), SQLAlchemy 2, Alembic. Local SQLite is the default; an external PostgreSQL database can be selected by explicitly setting `DATABASE_URL`.

## Database configuration

- **Default:** SQLite database at `./ehcc.db`.
- **Custom local path:** set `SQLITE_DB_PATH`, preferably to an absolute path for server deployments. Example: `SQLITE_DB_PATH=/opt/apps/EHCC/DB/ehcc-admin.db`.
- **Explicit database URL:** a non-empty `DATABASE_URL` takes precedence over `SQLITE_DB_PATH`. It can point to SQLite (for example, `sqlite:////opt/apps/EHCC/DB/ehcc-admin.db`) or PostgreSQL.
- PostgreSQL `postgres://` and `postgresql://` URLs are accepted and normalized automatically.
- If `DATABASE_URL` is absent or blank, the app uses the local SQLite path. No external database is contacted by default.

The application and Alembic create the parent directory for a file-based SQLite database when needed. SQLite connections enable foreign-key enforcement and a 30-second busy timeout.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
export ADMIN_PASSWORD=change-me SECRET_KEY=any-long-random-string
alembic upgrade head
uvicorn app.main:app --reload
```

Open http://localhost:8000, log in from the top bar with your name and the admin password, then create a team in Settings.

Tests: `pytest`. To run them against Postgres: `TEST_DATABASE_URL=postgresql://user:pass@localhost/ehcc_test pytest`.

## Deploy on EC2

1. Clone the repository into the app's dedicated directory.
2. Create the app-specific database directory.
3. Configure the environment in the app's private `.env` file. The six deployment keys below mirror the Render environment-variable names; keep their values private.
4. For local SQLite, set `DATABASE_URL` to the SQLite URL for the persistent EC2 database. Alternatively, leave `DATABASE_URL` blank and set `SQLITE_DB_PATH`.
5. Run `alembic upgrade head`, then start Uvicorn through the app's systemd service.

Example using the six Render variable names plus the app's required local settings:

```env
ADMIN_PASSWORD=replace-with-existing-admin-password
ADMIN_USERNAME=your-admin-username
DATABASE_URL=sqlite:////home/ubuntu/webapps/ehcc/db/ehcc-admin.db
PYTHON_VERSION=3.12.16
VIEW_ACCESS_PWD=replace-with-view-access-password
VIEW_ACCESS_USER=your-view-access-username
APP_ENV=production
SECRET_KEY=replace-with-a-long-random-secret
SHOW_MOBILE_TO_VIEWERS=0
```

**Current application support:** the application currently reads `ADMIN_PASSWORD` and `DATABASE_URL` from this six-key set. `ADMIN_USERNAME`, `VIEW_ACCESS_PWD`, and `VIEW_ACCESS_USER` are not currently referenced by the application code, and `PYTHON_VERSION` is deployment metadata rather than an application setting. Defining those variables in `.env` preserves the Render key set but does not, by itself, enable username-based admin login or separate view-only authentication. Do not assume those access controls are active until implemented in the application.

Use a strong, EC2-specific `SECRET_KEY`; do not reuse a development secret. Keep `.env` out of Git.

## Deploy with an external PostgreSQL database

Set a non-empty `DATABASE_URL` (for example, a Neon connection string) and run `alembic upgrade head` before starting the server. This explicitly overrides `SQLITE_DB_PATH`.

## Environment variables

### Render / deployment keys

| Variable | Purpose / current application behavior |
|---|---|
| `ADMIN_PASSWORD` | Shared admin password. Admin login is disabled if unset; this is read by the application. |
| `ADMIN_USERNAME` | Present in the Render configuration; not currently read by the application. Admins currently enter their name at login. |
| `DATABASE_URL` | Optional explicit database URL. A non-empty value overrides `SQLITE_DB_PATH`; supports SQLite and PostgreSQL. |
| `PYTHON_VERSION` | Deployment/runtime version metadata; not read by the application. |
| `VIEW_ACCESS_PWD` | Present in the Render configuration; not currently read by the application. |
| `VIEW_ACCESS_USER` | Present in the Render configuration; not currently read by the application. |

### Additional application settings

| Variable | Purpose |
|---|---|
| `SQLITE_DB_PATH` | Local SQLite file path used when `DATABASE_URL` is absent or blank; defaults to `./ehcc.db`. |
| `SECRET_KEY` | Signs session cookies. Required in production. |
| `APP_ENV` | `production` turns on secure cookies. |
| `SHOW_MOBILE_TO_VIEWERS` | `1` shows full mobile numbers to view-only visitors. Default is masked. |

## How the rules are implemented

- **Access:** anyone can view; only a logged-in admin can change anything. Every mutating route checks the admin session and a CSRF token on the server. Admins enter their name at login, and it is stamped on the audit log.
- **Teams:** creating a team creates its own team account in the same transaction. All accounts in a transaction must belong to that transaction's team, enforced in the service layer.
- **Allocation:** `CEILING((amount / parties) / step) * step`, with `step` a setting (default ₹5, Settings > Allocation rounding). A single party is charged the exact amount. The rounding difference is recorded as a team-account balance transfer once collections are complete; it is not shown as a separate balance.
- **Balances:** always derived from active transactions, never stored. Player net outstanding is shown as paid minus owed (minus means the player owes the team), where paid = expenses and income the player fronted + transfers out of the player - transfers into the player. Team account balance = starting balance + income + transfers in - transfers out - expenses paid by the team account.
- **Settlement:** reimbursement (team account to player) and collection (player to team account) each create one full transfer, linked through the `settlements` table. A partial unique index allows one active settlement per expense, party and kind, so duplicates fail at the database. Both operations run inside a database transaction with row locks.
- **Net settlement:** reimbursement and collection are independent, and each warns if the player also has the opposite pending. On a player's page, **Settle net** pays only the difference in one transfer and marks every pending reimbursement and collection settled in a single batch. Undoing any item undoes the whole batch. A difference of zero settles the items with no cash transfer.
- **Void / reversal:** nothing in the ledger is hard-deleted by normal use. Voiding an expense reverses its linked settlements (status `reversed`) and reopens nothing else. Voiding a settlement transfer reverses just that settlement. Editing is blocked while a transaction has active settlements.
- **Audit:** `audit_log` is append-only, enforced by a database trigger on Postgres and SQLite.
- **Data reset:** deletes transactions, allocations and settlements (all, or those recorded at or after a chosen time). Teams, players, categories and starting balances stay. The audit log is kept and records the reset.
