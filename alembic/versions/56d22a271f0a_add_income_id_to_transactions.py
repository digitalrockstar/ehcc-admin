"""add income_id to transactions

Revision ID: 56d22a271f0a
Revises: 1d7c42796f49
Create Date: 2026-09-06 08:36:35.242940

"""
from alembic import op
import sqlalchemy as sa


revision = '56d22a271f0a'
down_revision = '1d7c42796f49'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('income_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_transactions_income_id', 'adhoc_income', ['income_id'], ['id'])


def downgrade():
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_constraint('fk_transactions_income_id', type_='foreignkey')
        batch_op.drop_column('income_id')
