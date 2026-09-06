from datetime import date
from sqlalchemy.orm import Session
from .. import models
from .calculations import allocate_expense


def create_team_expense(db: Session, team_id: int, expense_date: date, category: str,
                         amount: float, payment_source: str, paid_by_player_id: int = None) -> models.TeamExpense:
    reimbursement_status = models.ReimbursementStatus.na
    if payment_source == models.PaymentSource.player.value:
        reimbursement_status = models.ReimbursementStatus.due

    expense = models.TeamExpense(
        team_id=team_id, date=expense_date, category=category, amount=amount,
        payment_source=payment_source, paid_by_player_id=paid_by_player_id,
        reimbursement_status=reimbursement_status,
    )
    db.add(expense)
    db.flush()

    if payment_source == models.PaymentSource.account.value:
        db.add(models.Transaction(
            team_id=team_id, date=expense_date, type=models.TransactionType.team_expense_account,
            amount=-float(amount), expense_id=expense.id, description=f"Team expense - {category}",
        ))

    db.commit()
    db.refresh(expense)
    return expense


def allocate_expense_to_players(db: Session, expense_id: int, player_ids_in_order: list) -> list:
    expense = db.query(models.TeamExpense).get(expense_id)
    shares = allocate_expense(int(expense.amount), player_ids_in_order)
    allocations = []
    for pid in player_ids_in_order:
        alloc = models.ExpenseAllocation(expense_id=expense_id, player_id=pid, amount=shares[pid])
        db.add(alloc)
        allocations.append(alloc)
    db.commit()
    for a in allocations:
        db.refresh(a)
    return allocations


def pay_expense_allocation(db: Session, allocation_id: int, payment_date: date = None) -> models.ExpenseAllocation:
    alloc = db.query(models.ExpenseAllocation).get(allocation_id)
    alloc.status = models.PaymentStatus.paid
    alloc.payment_date = payment_date or date.today()
    db.add(models.Transaction(
        team_id=alloc.expense.team_id, date=alloc.payment_date,
        type=models.TransactionType.player_receivable_paid, amount=float(alloc.amount),
        party_player_id=alloc.player_id, expense_id=alloc.expense_id,
        description=f"Receivable paid - {alloc.player.name}",
    ))
    db.commit()
    db.refresh(alloc)
    return alloc


def reimburse_player_for_expense(db: Session, expense_id: int, payment_date: date = None) -> models.Reimbursement:
    expense = db.query(models.TeamExpense).get(expense_id)
    reimb = models.Reimbursement(
        expense_id=expense_id, player_id=expense.paid_by_player_id,
        amount=expense.amount, date=payment_date or date.today(),
    )
    db.add(reimb)
    expense.reimbursement_status = models.ReimbursementStatus.paid
    db.add(models.Transaction(
        team_id=expense.team_id, date=reimb.date, type=models.TransactionType.reimbursement,
        amount=-float(expense.amount), party_player_id=expense.paid_by_player_id,
        expense_id=expense_id, description=f"Reimbursement - {expense.paid_by.name}",
    ))
    db.commit()
    db.refresh(reimb)
    return reimb


def update_team_expense(db: Session, expense_id: int, category: str, amount: float,
                         payment_source: str, paid_by_player_id: int = None) -> models.TeamExpense:
    expense = db.query(models.TeamExpense).get(expense_id)
    if expense.reimbursement_status == models.ReimbursementStatus.paid:
        raise ValueError("Undo the reimbursement before editing this expense.")

    account_txn = db.query(models.Transaction).filter(
        models.Transaction.type == models.TransactionType.team_expense_account,
        models.Transaction.expense_id == expense_id,
    ).first()

    if payment_source == models.PaymentSource.account.value:
        if account_txn:
            account_txn.amount = -float(amount)
        else:
            db.add(models.Transaction(
                team_id=expense.team_id, date=expense.date, type=models.TransactionType.team_expense_account,
                amount=-float(amount), expense_id=expense.id, description=f"Team expense - {category}",
            ))
    elif account_txn:
        db.delete(account_txn)

    expense.category = category
    expense.amount = amount
    expense.payment_source = payment_source
    expense.paid_by_player_id = paid_by_player_id if payment_source == models.PaymentSource.player.value else None
    expense.reimbursement_status = (
        models.ReimbursementStatus.due if payment_source == models.PaymentSource.player.value
        else models.ReimbursementStatus.na
    )
    db.commit()
    db.refresh(expense)
    return expense


def delete_team_expense(db: Session, expense_id: int) -> None:
    expense = db.query(models.TeamExpense).get(expense_id)
    if expense.reimbursement_status == models.ReimbursementStatus.paid:
        raise ValueError("Undo the reimbursement before deleting this expense.")
    db.query(models.Transaction).filter(models.Transaction.expense_id == expense_id).delete()
    db.query(models.ExpenseAllocation).filter(models.ExpenseAllocation.expense_id == expense_id).delete()
    db.delete(expense)
    db.commit()


def undo_reimbursement(db: Session, expense_id: int) -> models.TeamExpense:
    expense = db.query(models.TeamExpense).get(expense_id)
    if expense.reimbursement:
        db.query(models.Transaction).filter(
            models.Transaction.type == models.TransactionType.reimbursement,
            models.Transaction.expense_id == expense_id,
        ).delete()
        db.delete(expense.reimbursement)
    expense.reimbursement_status = models.ReimbursementStatus.due
    db.commit()
    db.refresh(expense)
    return expense
def add_adhoc_income(db: Session, team_id: int, income_date: date, income_type: str,
                      amount: float, match_id: int = None, notes: str = None) -> models.AdHocIncome:
    income = models.AdHocIncome(
        team_id=team_id, date=income_date, income_type=income_type,
        amount=amount, match_id=match_id, notes=notes,
    )
    db.add(income)
    db.flush()
    db.add(models.Transaction(
        team_id=team_id, date=income_date, type=models.TransactionType.adhoc_income,
        amount=float(amount), description=f"Ad hoc income - {income_type}",
    ))
    db.commit()
    db.refresh(income)
    return income
