from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
                        Numeric, String, Text, func, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TXN_TYPES = ("income", "expense", "transfer")
TXN_STATUSES = ("active", "voided", "reversed")
MONEY = Numeric(12, 2)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("status in ('active','archived')", name="ck_teams_status"),)


Index("uq_teams_name", func.lower(Team.name), unique=True)


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    player_name: Mapped[str] = mapped_column(String(80))
    mob_no: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    team: Mapped[Team] = relationship()
    account: Mapped["Account"] = relationship(back_populates="player", uselist=False)
    __table_args__ = (CheckConstraint("status in ('active','archived')", name="ck_players_status"),)


Index("uq_players_team_name", Player.team_id, func.lower(Player.player_name), unique=True)


class Account(Base):
    """One row per player plus exactly one per team (kind='team')."""
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    kind: Mapped[str] = mapped_column(String(6))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="active")
    team: Mapped[Team] = relationship()
    player: Mapped[Player | None] = relationship(back_populates="account")
    __table_args__ = (
        CheckConstraint("kind in ('team','player')", name="ck_accounts_kind"),
        CheckConstraint("status in ('active','archived')", name="ck_accounts_status"),
        CheckConstraint("(kind = 'team' and player_id is null) or (kind = 'player' and player_id is not null)",
                        name="ck_accounts_shape"),
    )

    @property
    def name(self) -> str:
        return self.player.player_name if self.kind == "player" else f"{self.team.name} account"


Index("uq_one_team_account", Account.team_id, unique=True,
      postgresql_where=text("kind = 'team'"), sqlite_where=text("kind = 'team'"))


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(7))
    is_other: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="active")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        CheckConstraint("kind in ('income','expense')", name="ck_categories_kind"),
        CheckConstraint("status in ('active','archived')", name="ck_categories_status"),
    )


Index("uq_categories_kind_name", Category.kind, func.lower(Category.name), unique=True)


class OpeningBalance(Base):
    __tablename__ = "opening_balances"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    transaction_date: Mapped[dt.date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(10))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    item_description: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    surplus_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_by: Mapped[str | None] = mapped_column(String(60))
    voided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[str | None] = mapped_column(String(60))
    void_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    team: Mapped[Team] = relationship()
    category: Mapped[Category | None] = relationship()
    accounts: Mapped[list["TransactionAccount"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan")
    allocations: Mapped[list["Allocation"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan",
        foreign_keys="Allocation.transaction_id")

    __table_args__ = (
        CheckConstraint("type in ('income','expense','transfer')", name="ck_transactions_type"),
        CheckConstraint("status in ('active','voided','reversed')", name="ck_transactions_status"),
        CheckConstraint("amount > 0", name="ck_transactions_amount"),
        Index("ix_transactions_team_date", "team_id", "transaction_date"),
    )

    def party(self, role: str) -> list["Account"]:
        return [ta.account for ta in self.accounts if ta.role == role]


class TransactionAccount(Base):
    """Payer / recipient / transfer legs. Roles: paid_by, account_in, account_out."""
    __tablename__ = "transaction_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))
    transaction: Mapped[Transaction] = relationship(back_populates="accounts")
    account: Mapped[Account] = relationship()
    __table_args__ = (
        CheckConstraint("role in ('paid_by','account_in','account_out')", name="ck_txn_accounts_role"),
        Index("uq_txn_account_role", "transaction_id", "account_id", "role", unique=True),
    )


class Allocation(Base):
    __tablename__ = "allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    allocated_amount: Mapped[Decimal] = mapped_column(MONEY)
    settlement_status: Mapped[int] = mapped_column(Integer, default=0)
    settled_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    transaction: Mapped[Transaction] = relationship(back_populates="allocations",
                                                    foreign_keys=[transaction_id])
    account: Mapped[Account] = relationship()
    __table_args__ = (
        CheckConstraint("settlement_status in (0, 1)", name="ck_allocations_settlement"),
        CheckConstraint("allocated_amount > 0", name="ck_allocations_amount"),
        Index("uq_allocation_party", "transaction_id", "account_id", unique=True),
    )


class Settlement(Base):
    """Full reimbursement or full collection. Never partial."""
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(13))
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    allocation_id: Mapped[int | None] = mapped_column(ForeignKey("allocations.id", ondelete="SET NULL"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    settlement_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reversed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    account: Mapped[Account] = relationship()
    __table_args__ = (
        CheckConstraint("kind in ('reimbursement','collection')", name="ck_settlements_kind"),
        CheckConstraint("status in ('active','reversed')", name="ck_settlements_status"),
    )


# Duplicate protection lives in the database: one active settlement per parent, party and kind.
Index("uq_active_settlement", Settlement.transaction_id, Settlement.account_id, Settlement.kind,
      unique=True, postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'"))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    team_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
