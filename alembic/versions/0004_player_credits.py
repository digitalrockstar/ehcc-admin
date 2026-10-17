"""player credits and repeat collections after edits

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_active_settlement", table_name="settlements")
    op.create_index("uq_active_reimbursement", "settlements", ["transaction_id", "account_id"], unique=True,
                    postgresql_where=sa.text("status = 'active' AND kind = 'reimbursement'"),
                    sqlite_where=sa.text("status = 'active' AND kind = 'reimbursement'"))
    op.create_index("uq_active_team_balance", "settlements", ["transaction_id", "kind"], unique=True,
                    postgresql_where=sa.text("status = 'active' AND kind = 'team_balance'"),
                    sqlite_where=sa.text("status = 'active' AND kind = 'team_balance'"))
    op.create_table(
        "player_credits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("source_transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("remaining_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("original_amount > 0", name="ck_player_credits_original_amount"),
        sa.CheckConstraint("remaining_amount >= 0 AND remaining_amount <= original_amount", name="ck_player_credits_remaining_amount"),
        sa.UniqueConstraint("source_transaction_id", "account_id", name="uq_player_credit_source_account"),
    )
    op.create_index("ix_player_credits_team_id", "player_credits", ["team_id"])
    op.create_index("ix_player_credits_account_id", "player_credits", ["account_id"])
    op.create_index("uq_player_credit_source_account", "player_credits", ["source_transaction_id", "account_id"], unique=True)
    op.create_table(
        "player_credit_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("credit_id", sa.Integer(), sa.ForeignKey("player_credits.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("allocation_id", sa.Integer(), sa.ForeignKey("allocations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind in ('created','application','team_transfer','adjustment')", name="ck_player_credit_movements_kind"),
        sa.CheckConstraint("amount > 0", name="ck_player_credit_movements_amount"),
    )
    op.create_index("ix_player_credit_movements_credit_id", "player_credit_movements", ["credit_id"])


def downgrade() -> None:
    op.drop_table("player_credit_movements")
    op.drop_table("player_credits")
    op.drop_index("uq_active_team_balance", table_name="settlements")
    op.drop_index("uq_active_reimbursement", table_name="settlements")
    op.create_index("uq_active_settlement", "settlements", ["transaction_id", "account_id", "kind"], unique=True,
                    postgresql_where=sa.text("status = 'active'"),
                    sqlite_where=sa.text("status = 'active'"))
