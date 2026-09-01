"""invitations and mfa

Revision ID: 7a1f3c9de2b4
Revises: 2e34ebd5bda1
Create Date: 2026-09-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.types


# revision identifiers, used by Alembic.
revision: str = '7a1f3c9de2b4'
down_revision: Union[str, None] = '2e34ebd5bda1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('mfa_code_hash', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('mfa_code_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('mfa_attempts', sa.Integer(), server_default='0', nullable=False))

    op.create_table(
        'invitations',
        sa.Column('id', app.types.GUID(), nullable=False),
        sa.Column('organisation_id', app.types.GUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('invited_by_id', app.types.GUID(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['invited_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organisation_id'], ['organisations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invitations_email'), 'invitations', ['email'], unique=False)
    op.create_index(op.f('ix_invitations_token'), 'invitations', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_invitations_token'), table_name='invitations')
    op.drop_index(op.f('ix_invitations_email'), table_name='invitations')
    op.drop_table('invitations')
    op.drop_column('users', 'mfa_attempts')
    op.drop_column('users', 'mfa_code_expires_at')
    op.drop_column('users', 'mfa_code_hash')
