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


def _indexes(table_name: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("settlements"):
        if "uq_active_settlement" in _indexes("settlements"):
            op.drop_index("uq_active_settlement", table_name="settlements")
        if "uq_active_reimbursement" not in _indexes("settlements"):
            op.create_index(
                "uq_active_reimbursement", "settlements", ["transaction_id", "account_id"], unique=True,
                postgresql_where=sa.text("status = 'active' AND kind = 'reimbursement'"),
                sqlite_where=sa.text("status = 'active' AND kind = 'reimbursement'"))
        if "uq_active_team_balance" not in _indexes("settlements"):
            op.create_index(
                "uq_active_team_balance", "settlements", ["transaction_id", "kind"], unique=True,
                postgresql_where=sa.text("status = 'active' AND kind = 'team_balance'"),
                sqlite_where=sa.text("status = 'active' AND kind = 'team_balance'"))

    inspector = sa.inspect(bind)
    if not inspector.has_table("player_credits"):
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
            sa.CheckConstraint("remaining_amount >= 0 AND remaining_amount <= original_amount",
                               name="ck_player_credits_remaining_amount"),
        )
    inspector = sa.inspect(bind)
    if not inspector.has_table("player_credit_movements"):
        op.create_table(
            "player_credit_movements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("credit_id", sa.Integer(), sa.ForeignKey("player_credits.id"), nullable=False),
            sa.Column("kind", sa.String(12), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("allocation_id", sa.Integer(), sa.ForeignKey("allocations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("kind in ('created','application','team_transfer','adjustment')",
                               name="ck_player_credit_movements_kind"),
            sa.CheckConstraint("amount > 0", name="ck_player_credit_movements_amount"),
        )
    else:
        cols = {c["name"] for c in sa.inspect(bind).get_columns("player_credit_movements")}
        if "reversed_at" not in cols:
            op.add_column("player_credit_movements", sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))

    for table, name, cols, unique in (
        ("player_credits", "ix_player_credits_team_id", ["team_id"], False),
        ("player_credits", "ix_player_credits_account_id", ["account_id"], False),
        ("player_credits", "uq_player_credit_source_account", ["source_transaction_id", "account_id"], True),
        ("player_credit_movements", "ix_player_credit_movements_credit_id", ["credit_id"], False),
    ):
        if name not in _indexes(table):
            op.create_index(name, table, cols, unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text(
        "SELECT COUNT(*) FROM player_credits WHERE remaining_amount < original_amount"
    )).scalar():
        raise RuntimeError("Cannot downgrade: player credits have been applied or transferred.")
    inspector = sa.inspect(bind)
    if inspector.has_table("player_credit_movements"):
        op.drop_table("player_credit_movements")
    if inspector.has_table("player_credits"):
        op.drop_table("player_credits")
    if inspector.has_table("settlements"):
        indexes = _indexes("settlements")
        if "uq_active_team_balance" in indexes:
            op.drop_index("uq_active_team_balance", table_name="settlements")
        if "uq_active_reimbursement" in indexes:
            op.drop_index("uq_active_reimbursement", table_name="settlements")
        if "uq_active_settlement" not in _indexes("settlements"):
            op.create_index("uq_active_settlement", "settlements",
                            ["transaction_id", "account_id", "kind"], unique=True,
                            postgresql_where=sa.text("status = 'active'"),
                            sqlite_where=sa.text("status = 'active'"))
