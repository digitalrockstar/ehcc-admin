from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .database import Base, engine
from .routers import dashboard, teams, players, matches, expenses, reimbursements, income, reports

Base.metadata.create_all(bind=engine)

app = FastAPI(title="EHCC Accounts")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(teams.router)
app.include_router(dashboard.router)
app.include_router(players.router)
app.include_router(matches.router)
app.include_router(expenses.router)
app.include_router(reimbursements.router)
app.include_router(income.router)
app.include_router(reports.router)
