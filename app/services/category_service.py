from sqlalchemy.orm import Session
from .. import models

DEFAULT_EXPENSE_CATEGORIES = ["Cricket Balls", "Gloves", "Stumps", "Bats", "Jerseys", "Equipment", "Other Team Expenses"]
DEFAULT_INCOME_TYPES = ["Team Contribution", "Sponsorship", "Donation", "Miscellaneous Income"]


def ensure_default_categories(db: Session, team_id: int) -> None:
    existing = {c.name for c in db.query(models.ExpenseCategory).filter(models.ExpenseCategory.team_id == team_id)}
    for name in DEFAULT_EXPENSE_CATEGORIES:
        if name not in existing:
            db.add(models.ExpenseCategory(team_id=team_id, name=name))
    db.commit()


def ensure_default_income_types(db: Session, team_id: int) -> None:
    existing = {t.name for t in db.query(models.IncomeType).filter(models.IncomeType.team_id == team_id)}
    for name in DEFAULT_INCOME_TYPES:
        if name not in existing:
            db.add(models.IncomeType(team_id=team_id, name=name))
    db.commit()


def list_expense_categories(db: Session, team_id: int) -> list:
    ensure_default_categories(db, team_id)
    return db.query(models.ExpenseCategory).filter(models.ExpenseCategory.team_id == team_id).order_by(
        models.ExpenseCategory.name
    ).all()


def list_income_types(db: Session, team_id: int) -> list:
    ensure_default_income_types(db, team_id)
    return db.query(models.IncomeType).filter(models.IncomeType.team_id == team_id).order_by(
        models.IncomeType.name
    ).all()
