"""allow team-balance rounding settlements

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode handles SQLite and PostgreSQL while preserving settlement rows.
    with op.batch_alter_table("settlements") as batch:
        batch.drop_constraint("ck_settlements_kind", type_="check")
        batch.create_check_constraint(
            "ck_settlements_kind",
            "kind in ('reimbursement','collection','team_balance')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM settlements WHERE kind = 'team_balance'")).scalar():
        raise RuntimeError("Cannot downgrade: team_balance settlements exist.")
    with op.batch_alter_table("settlements") as batch:
        batch.drop_constraint("ck_settlements_kind", type_="check")
        batch.create_check_constraint(
            "ck_settlements_kind", "kind in ('reimbursement','collection')"
        )
