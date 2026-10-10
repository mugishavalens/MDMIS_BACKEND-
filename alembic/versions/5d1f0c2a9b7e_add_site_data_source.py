"""add site data_source (attribution for imported sites)

Revision ID: 5d1f0c2a9b7e
Revises: e847b260f14e
Create Date: 2026-10-09 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.types  # needed for the custom GUID type used on every PK/FK


# revision identifiers, used by Alembic.
revision: str = '5d1f0c2a9b7e'
down_revision: Union[str, None] = 'e847b260f14e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Kept as a server default (not dropped afterwards) so this also runs on
    # SQLite, which can't ALTER COLUMN ... DROP DEFAULT.
    op.add_column('sites', sa.Column('data_source', sa.String(length=200), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('sites', 'data_source')
