from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Numeric, Date, DateTime, Boolean,
    ForeignKey, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from .database import Base


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    starting_balance = Column(Numeric(12, 2), nullable=False, default=0)
    is_archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", uselist=False, back_populates="team")
    players = relationship("Player", back_populates="team")


class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    player_name = Column(String, nullable=False)
    mob_no = Column(String, nullable=True)
    is_archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    team = relationship("Team", back_populates="players")
    account = relationship("Account", uselist=False, back_populates="player")


class Account(Base):
    """Unifies team accounts and player accounts so either can be used
    anywhere an account/party is required (Section 4/8)."""
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False)  # 'team' | 'player'
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True, unique=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True, unique=True)

    team = relationship("Team", back_populates="account")
    player = relationship("Player", back_populates="account")

    @property
    def display_name(self):
        if self.kind == "team":
            return self.team.name if self.team else "Team account"
        return self.player.player_name if self.player else "Player"


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    type = Column(String, nullable=False)  # 'income' | 'expense'
    name = Column(String, nullable=False)
    is_archived = Column(Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("type", "name", name="uq_category_type_name"),)


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    transaction_date = Column(Date, nullable=False, default=date.today)
    type = Column(String, nullable=False)  # 'income' | 'expense' | 'transfer'
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    item_description = Column(String, nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String, nullable=False, default="active")  # active|voided|reversed
    reversal_of_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    surplus_amount = Column(Numeric(12, 2), nullable=False, default=0)

    # who physically paid / who is the transfer source (single account)
    payer_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    # transfer destination (single account); for income, recipient is always the team account
    recipient_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = relationship("Team")
    category = relationship("Category")
    payer_account = relationship("Account", foreign_keys=[payer_account_id])
    recipient_account = relationship("Account", foreign_keys=[recipient_account_id])
    allocations = relationship("Allocation", back_populates="transaction", foreign_keys="Allocation.transaction_id")


class Allocation(Base):
    """Per-account amount owed arising from an expense charged to one or
    more players, or a payable owed to a player who personally paid.
    direction: 'receivable' (account owes team) or 'payable' (team owes account)."""
    __tablename__ = "allocations"
    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    direction = Column(String, nullable=False)  # 'receivable' | 'payable'
    allocated_amount = Column(Numeric(12, 2), nullable=False)
    settlement_status = Column(Integer, nullable=False, default=0)  # 0 or 1
    settled_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    transaction = relationship("Transaction", back_populates="allocations", foreign_keys=[transaction_id])
    account = relationship("Account")
    settled_transaction = relationship("Transaction", foreign_keys=[settled_transaction_id])


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    actor = Column(String, nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ts = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)
