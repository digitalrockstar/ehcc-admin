"""net settlement batches

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settlements", sa.Column("batch_id", sa.String(length=32), nullable=True))
    op.create_index("ix_settlements_batch_id", "settlements", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_settlements_batch_id", table_name="settlements")
    with op.batch_alter_table("settlements") as batch:
        batch.drop_column("batch_id")
