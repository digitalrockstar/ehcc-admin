# EHCC Accounts

Team accounts, match fees, player receivables/payables, and additional
income tracking for a cricket team. Built against the product requirements
in `EHCC_Accounts___Product_Requirements.md`.

## Stack

FastAPI + SQLAlchemy + Alembic, Jinja2 + HTMX + Tailwind (CDN) for the UI,
Postgres (Neon) in production, SQLite for local dev.

## Local development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # edit as needed; sqlite works out of the box
uvicorn app.main:app --reload
```

Visit `http://localhost:8000`. On sqlite, tables are created automatically.
Auth is skipped locally unless you set `ADMIN_USERNAME`/`ADMIN_PASSWORD`.

## Tests

```bash
pytest tests/ -q
python scripts/verify_e2e.py   # runs the full PRD Section 45 acceptance flow
```

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

## Known gaps (documented, not hidden)

- Match editing (PRD Section 38 - recalculating fees on an already-paid
  match with a confirmation step) is not yet built.
- Only one visual theme exists so far; PRD Section 41 lists eight.
- Single-admin auth only (HTTP Basic). No per-player login, no multi-team
  support yet - both are explicitly future expansion in Section 47.
