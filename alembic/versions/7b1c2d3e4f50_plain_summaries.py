"""plain-language summaries for the What's left page

Revision ID: 7b1c2d3e4f50
Revises: 4e0296359a5a
Create Date: 2026-11-13 20:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7b1c2d3e4f50'
down_revision: Union[str, Sequence[str], None] = '4e0296359a5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('plain_summaries', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'plain_summaries')
