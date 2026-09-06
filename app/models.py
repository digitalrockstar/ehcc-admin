import enum
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Numeric, Date, DateTime, ForeignKey, Enum, Text, Boolean
)
from sqlalchemy.orm import relationship
from .database import Base


class MatchStatus(str, enum.Enum):
    upcoming = "upcoming"
    completed = "completed"
    cancelled = "cancelled"


class PaymentStatus(str, enum.Enum):
    due = "due"
    paid = "paid"


class PaymentSource(str, enum.Enum):
    account = "account"
    player = "player"


class ReimbursementStatus(str, enum.Enum):
    na = "na"
    due = "due"
    paid = "paid"


class PlayerStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    starting_balance = Column(Numeric(12, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    players = relationship("Player", back_populates="team")
    matches = relationship("Match", back_populates="team")


class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    name = Column(String, nullable=False)
    contact_number = Column(String, nullable=True)
    status = Column(Enum(PlayerStatus), default=PlayerStatus.active, nullable=False)

    team = relationship("Team", back_populates="players")


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    name = Column(String, nullable=False)


class IncomeType(Base):
    __tablename__ = "income_types"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    name = Column(String, nullable=False)


class Match(Base):
    __tablename__ = "matches"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    match_date = Column(Date, nullable=False)
    status = Column(Enum(MatchStatus), default=MatchStatus.upcoming, nullable=False)
    notes = Column(Text, nullable=True)
    ground_fees = Column(Numeric(12, 2), nullable=False, default=0)
    additional_amount = Column(Numeric(12, 2), nullable=False, default=0)
    expense_paid_from_account = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    team = relationship("Team", back_populates="matches")
    participants = relationship("MatchParticipant", back_populates="match", cascade="all, delete-orphan")

    @property
    def total_expense(self):
        return self.ground_fees + self.additional_amount


class MatchParticipant(Base):
    __tablename__ = "match_participants"
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    fee_amount = Column(Numeric(12, 2), nullable=False)
    amount_paid = Column(Numeric(12, 2), nullable=True)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.due, nullable=False)
    payment_date = Column(Date, nullable=True)

    match = relationship("Match", back_populates="participants")
    player = relationship("Player")


class TeamExpense(Base):
    __tablename__ = "team_expenses"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    date = Column(Date, nullable=False)
    category = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    payment_source = Column(Enum(PaymentSource), nullable=False)
    paid_by_player_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    reimbursement_status = Column(Enum(ReimbursementStatus), default=ReimbursementStatus.na, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    paid_by = relationship("Player", foreign_keys=[paid_by_player_id])
    allocations = relationship("ExpenseAllocation", back_populates="expense", cascade="all, delete-orphan")
    reimbursement = relationship("Reimbursement", back_populates="expense", uselist=False)


class ExpenseAllocation(Base):
    __tablename__ = "expense_allocations"
    id = Column(Integer, primary_key=True)
    expense_id = Column(Integer, ForeignKey("team_expenses.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.due, nullable=False)
    payment_date = Column(Date, nullable=True)

    expense = relationship("TeamExpense", back_populates="allocations")
    player = relationship("Player")


class Reimbursement(Base):
    __tablename__ = "reimbursements"
    id = Column(Integer, primary_key=True)
    expense_id = Column(Integer, ForeignKey("team_expenses.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    date = Column(Date, nullable=False)

    expense = relationship("TeamExpense", back_populates="reimbursement")
    player = relationship("Player")


class AdHocIncome(Base):
    __tablename__ = "adhoc_income"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    date = Column(Date, nullable=False)
    income_type = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    notes = Column(Text, nullable=True)


class TransactionType(str, enum.Enum):
    starting_balance = "starting_balance"
    match_expense_account = "match_expense_account"
    match_fee_paid = "match_fee_paid"
    team_expense_account = "team_expense_account"
    player_receivable_paid = "player_receivable_paid"
    reimbursement = "reimbursement"
    adhoc_income = "adhoc_income"


class Transaction(Base):
    """Single source of truth ledger. Every actual cash movement affecting
    the Team account is recorded here exactly once (Section 27 / 44)."""
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    date = Column(Date, nullable=False, default=date.today)
    type = Column(Enum(TransactionType), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)  # signed: + inflow, - outflow
    party_player_id = Column(Integer, ForeignKey("players.id"), nullable=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=True)
    expense_id = Column(Integer, ForeignKey("team_expenses.id"), nullable=True)
    income_id = Column(Integer, ForeignKey("adhoc_income.id"), nullable=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
