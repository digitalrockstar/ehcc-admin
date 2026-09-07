import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .database import Base, engine, DATABASE_URL
from .routers import dashboard, teams, players, matches, expenses, reimbursements, income, reports, theme, settings, transactions

# Real deployments run `alembic upgrade head` before boot (see render.yaml).
# For local sqlite dev, auto-create so `uvicorn app.main:app` just works.
if DATABASE_URL.startswith("sqlite"):
    Base.metadata.create_all(bind=engine)

app = FastAPI(title="EHCC Accounts")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(theme.router)
app.include_router(teams.router)
app.include_router(dashboard.router)
app.include_router(players.router)
app.include_router(matches.router)
app.include_router(expenses.router)
app.include_router(reimbursements.router)
app.include_router(income.router)
app.include_router(reports.router)
app.include_router(transactions.router)
app.include_router(settings.router)
