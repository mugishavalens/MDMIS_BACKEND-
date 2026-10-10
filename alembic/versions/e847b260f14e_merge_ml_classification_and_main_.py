"""merge ml classification and main migration branches

Revision ID: e847b260f14e
Revises: b9cfac4615c8, bc12e5bf5308
Create Date: 2026-10-08 17:06:12.354591

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.types  # needed for the custom GUID type used on every PK/FK


# revision identifiers, used by Alembic.
revision: str = 'e847b260f14e'
down_revision: Union[str, None] = ('b9cfac4615c8', 'bc12e5bf5308')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
