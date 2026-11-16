"""create tables

# =============================================================================
# MIGRATION 0001  -  CREATES ALL TABLES (the first version of the database)
# =============================================================================
# `upgrade()`   moves the database FORWARD  (creates the tables)
# `downgrade()` moves the database BACK     (removes the tables)
# Run it with:  alembic upgrade head
#
# Note: in models.py dates use our own UTCDateTime type. In the database that
# is just a normal DateTime column, so we write sa.DateTime() here.
# Read more: docs/05-database.md
# =============================================================================

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('api_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('key_prefix', sa.String(length=12), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_api_keys_key_hash'), ['key_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_api_keys_user_id'), ['user_id'], unique=False)

    op.create_table('monitors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('interval_seconds', sa.Integer(), nullable=False),
    sa.Column('expected_status', sa.Integer(), nullable=False),
    sa.Column('failure_threshold', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('alert_webhook_url', sa.String(length=2048), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('consecutive_failures', sa.Integer(), nullable=False),
    sa.Column('last_checked_at', sa.DateTime(), nullable=True),
    sa.Column('next_check_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('monitors', schema=None) as batch_op:
        batch_op.create_index('ix_monitors_due', ['is_active', 'next_check_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_monitors_user_id'), ['user_id'], unique=False)

    op.create_table('check_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('monitor_id', sa.Integer(), nullable=False),
    sa.Column('checked_at', sa.DateTime(), nullable=False),
    sa.Column('is_up', sa.Boolean(), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('response_time_ms', sa.Integer(), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['monitor_id'], ['monitors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('check_results', schema=None) as batch_op:
        batch_op.create_index('ix_check_results_monitor_time', ['monitor_id', 'checked_at'], unique=False)

    op.create_table('incidents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('monitor_id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['monitor_id'], ['monitors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.create_index('ix_incidents_monitor_started', ['monitor_id', 'started_at'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.drop_index('ix_incidents_monitor_started')

    op.drop_table('incidents')
    with op.batch_alter_table('check_results', schema=None) as batch_op:
        batch_op.drop_index('ix_check_results_monitor_time')

    op.drop_table('check_results')
    with op.batch_alter_table('monitors', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_monitors_user_id'))
        batch_op.drop_index('ix_monitors_due')

    op.drop_table('monitors')
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_keys_user_id'))
        batch_op.drop_index(batch_op.f('ix_api_keys_key_hash'))

    op.drop_table('api_keys')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
