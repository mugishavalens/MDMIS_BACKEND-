"""add users.token_version (revocable tokens)

Revision ID: c4e7a1d9b250
Revises: 8f3b2d6c1a47
Create Date: 2026-11-12 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e7a1d9b250'
down_revision: Union[str, None] = '8f3b2d6c1a47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Server default kept (not dropped) so this also runs on SQLite, and so
    # code that predates the column keeps working against a migrated DB.
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('users', 'token_version')
