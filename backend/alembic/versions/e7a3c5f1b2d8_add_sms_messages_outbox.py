"""add sms_messages outbox table

Revision ID: e7a3c5f1b2d8
Revises: d5e8b0c2e4f6
Create Date: 2026-09-18 15:00:00.000000

Run via: cd backend && .venv/bin/alembic upgrade head
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a3c5f1b2d8'
down_revision: Union[str, Sequence[str], None] = 'd5e8b0c2e4f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the M31 SMS outbox table."""
    op.create_table(
        'sms_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('bill_id', sa.UUID(), nullable=True),
        sa.Column('customer_id', sa.UUID(), nullable=True),
        sa.Column('mobile', sa.String(length=30), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='QUEUED', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('provider', sa.String(length=20), server_default='msg91', nullable=False),
        sa.Column('gateway_response', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['store_id'], ['stores.id'], name=op.f('fk_sms_messages_store_id_stores'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['bill_id'], ['bills.id'], name=op.f('fk_sms_messages_bill_id_bills'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['customer_id'], ['customers.id'], name=op.f('fk_sms_messages_customer_id_customers'),
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sms_messages')),
    )
    op.create_index(
        op.f('ix_sms_messages_store_id'), 'sms_messages', ['store_id'], unique=False
    )
    op.create_index(
        op.f('ix_sms_messages_bill_id'), 'sms_messages', ['bill_id'], unique=False
    )
    op.create_index(
        'ix_sms_messages_store_status_due',
        'sms_messages',
        ['store_id', 'status', 'next_attempt_at'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the M31 SMS outbox table."""
    op.drop_index('ix_sms_messages_store_status_due', table_name='sms_messages')
    op.drop_index(op.f('ix_sms_messages_bill_id'), table_name='sms_messages')
    op.drop_index(op.f('ix_sms_messages_store_id'), table_name='sms_messages')
    op.drop_table('sms_messages')