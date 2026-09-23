from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .database import Base, engine, DATABASE_URL, SessionLocal
from .routers import dashboard, teams, players, transactions, settings, theme
from . import models

if DATABASE_URL.startswith("sqlite"):
    Base.metadata.create_all(bind=engine)

DEFAULT_EXPENSE_CATEGORIES = ["Bat", "Balls", "Gloves", "Ground Charges", "Jerseys", "Nets", "Stumps", "Other"]
DEFAULT_INCOME_CATEGORIES = ["Sponsorship", "Donation", "Misc.", "Team Contribution", "Other"]


def seed_categories():
    db = SessionLocal()
    try:
        existing = {(c.type, c.name) for c in db.query(models.Category).all()}
        for name in DEFAULT_EXPENSE_CATEGORIES:
            if ("expense", name) not in existing:
                db.add(models.Category(type="expense", name=name))
        for name in DEFAULT_INCOME_CATEGORIES:
            if ("income", name) not in existing:
                db.add(models.Category(type="income", name=name))
        db.commit()
    finally:
        db.close()


app = FastAPI(title="EHCC Accounts")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(theme.router)
app.include_router(teams.router)
app.include_router(dashboard.router)
app.include_router(players.router)
app.include_router(transactions.router)
app.include_router(settings.router)


@app.on_event("startup")
def on_startup():
    seed_categories()
