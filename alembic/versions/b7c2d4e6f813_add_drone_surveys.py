"""add drone_surveys (drone photos -> 3D block)

Revision ID: b7c2d4e6f813
Revises: a3d5e8f1b602
Create Date: 2026-11-18 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.types import GUID

revision: str = 'b7c2d4e6f813'
down_revision: Union[str, None] = 'a3d5e8f1b602'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'drone_surveys',
        sa.Column('id', GUID(), primary_key=True),
        sa.Column('organisation_id', GUID(), sa.ForeignKey('organisations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('site_id', sa.String(32), sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', GUID(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('label', sa.String(200), nullable=False, server_default=''),
        sa.Column('photo_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ml_job_id', sa.String(32), nullable=False, server_default=''),
        sa.Column('state', sa.String(10), nullable=False, server_default='queued'),
        sa.Column('stage', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('progress', sa.Float(), nullable=False, server_default='0'),
        sa.Column('message', sa.String(300), nullable=False, server_default=''),
        sa.Column('error', sa.String(500), nullable=False, server_default=''),
        sa.Column('stats', sa.JSON(), nullable=True),
        sa.Column('ground', sa.JSON(), nullable=True),
        sa.Column('surface', sa.JSON(), nullable=True),
        sa.Column('cloud', sa.JSON(), nullable=True),
        sa.Column('ortho', sa.LargeBinary(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_drone_surveys_site_id', 'drone_surveys', ['site_id'])


def downgrade() -> None:
    op.drop_index('ix_drone_surveys_site_id', table_name='drone_surveys')
    op.drop_table('drone_surveys')
