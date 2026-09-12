"""create alerts table

Revision ID: d9e4a30f8b21
Revises: b7f3d11e4a59
Create Date: 2026-09-07 09:15:00.000000

M16 — persistent, offline-first alert centre. Alerts are informational /
actionable notifications derived from existing intelligence; their lifecycle
status transitions are OPEN -> ACKNOWLEDGED -> RESOLVED, OPEN -> RESOLVED, or
OPEN -> DISMISSED (terminal). Evidence is metadata only (JSONB) — raw video is
never stored.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd9e4a30f8b21'
down_revision: Union[str, Sequence[str], None] = 'b7f3d11e4a59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'alerts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('camera_id', sa.UUID(), nullable=True),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('shelf_id', sa.UUID(), nullable=True),
        sa.Column('alert_type', sa.String(length=40), nullable=False),
        sa.Column('severity', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('message', sa.String(length=2000), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('source_type', sa.String(length=40), nullable=True),
        sa.Column('source_id', sa.String(length=100), nullable=True),
        sa.Column('first_detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['camera_id'],
            ['cameras.id'],
            name=op.f('fk_alerts_camera_id_cameras'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['product_id'],
            ['products.id'],
            name=op.f('fk_alerts_product_id_products'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['shelf_id'],
            ['shelves.id'],
            name=op.f('fk_alerts_shelf_id_shelves'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['store_id'],
            ['stores.id'],
            name=op.f('fk_alerts_store_id_stores'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_alerts')),
    )
    op.create_index(
        op.f('ix_alerts_alert_type'),
        'alerts',
        ['alert_type'],
        unique=False,
    )
    op.create_index(
        op.f('ix_alerts_camera_id'),
        'alerts',
        ['camera_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_alerts_last_detected_at'),
        'alerts',
        ['last_detected_at'],
        unique=False,
    )
    op.create_index(
        op.f('ix_alerts_product_id'),
        'alerts',
        ['product_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_alerts_severity'),
        'alerts',
        ['severity'],
        unique=False,
    )
    op.create_index(
        op.f('ix_alerts_shelf_id'),
        'alerts',
        ['shelf_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_alerts_status'),
        'alerts',
        ['status'],
        unique=False,
    )
    op.create_index(
        op.f('ix_alerts_store_id'),
        'alerts',
        ['store_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_alerts_store_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_status'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_shelf_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_severity'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_product_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_last_detected_at'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_camera_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_alert_type'), table_name='alerts')
    op.drop_table('alerts')