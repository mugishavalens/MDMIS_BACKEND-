"""add sites.is_shared; share the seeded demo sites with every organisation

Revision ID: a3d5e8f1b602
Revises: c4e7a1d9b250
Create Date: 2026-11-16 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3d5e8f1b602'
down_revision: Union[str, None] = 'c4e7a1d9b250'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The 10 demo sites from app/seed.py. Before this, every site belonged to the
# demo organisation only, so anyone who signed up (a new, empty organisation)
# saw no sites and no 3D blocks.
DEMO_SITE_IDS = (
    'RW-RTG-01', 'RW-GTB-02', 'RW-NYK-03', 'RW-GFW-04', 'RW-RWK-05',
    'RW-NMB-06', 'RW-BGR-07', 'RW-MSH-08', 'RW-KRG-09', 'RW-RTS-10',
)


def upgrade() -> None:
    op.add_column('sites', sa.Column('is_shared', sa.Boolean(), nullable=False, server_default=sa.false()))
    sites = sa.table('sites', sa.column('id', sa.String), sa.column('is_shared', sa.Boolean))
    op.execute(sites.update().where(sites.c.id.in_(DEMO_SITE_IDS)).values(is_shared=True))


def downgrade() -> None:
    op.drop_column('sites', 'is_shared')
