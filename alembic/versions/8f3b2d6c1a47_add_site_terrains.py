"""add site_terrains (3D block surface stored in the backend)

Revision ID: 8f3b2d6c1a47
Revises: 5d1f0c2a9b7e
Create Date: 2026-11-11 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f3b2d6c1a47'
down_revision: Union[str, None] = '5d1f0c2a9b7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'site_terrains',
        sa.Column('site_id', sa.String(length=32), nullable=False),
        sa.Column('grid', sa.JSON(), nullable=False),
        sa.Column('source', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('site_id'),
    )


def downgrade() -> None:
    op.drop_table('site_terrains')
