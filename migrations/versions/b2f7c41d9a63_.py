"""Add the week of the rules to games

Revision ID: b2f7c41d9a63
Revises: 63349a01d030
Create Date: 2026-11-02 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2f7c41d9a63'
down_revision = '63349a01d030'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('games', sa.Column('week', sa.Integer(), server_default='1', nullable=False))


def downgrade():
    op.drop_column('games', 'week')
