"""add shelf_snapshots table

Revision ID: d5e8b0c2e4f6
Revises: f4a9c0a1b2c3
Create Date: 2026-09-18 12:00:00.000000

Run via: cd backend && .venv/bin/alembic upgrade head
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'd5e8b0c2e4f6'
down_revision: Union[str, Sequence[str], None] = 'f4a9c0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the M30 periodic shelf-occupancy snapshot table."""
    op.create_table(
        'shelf_snapshots',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('camera_id', sa.UUID(), nullable=True),
        sa.Column('shelf_code', sa.String(length=30), nullable=False),
        sa.Column('shelf_label', sa.String(length=200), nullable=True),
        sa.Column('region_bbox', JSONB(), nullable=True),
        sa.Column('snapshot_path', sa.String(length=500), nullable=True),
        sa.Column('crop_path', sa.String(length=500), nullable=True),
        sa.Column('fill_percentage', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('product_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('occluded', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('occlusion_note', sa.String(length=200), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['store_id'], ['stores.id'], name=op.f('fk_shelf_snapshots_store_id_stores'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['camera_id'], ['cameras.id'], name=op.f('fk_shelf_snapshots_camera_id_cameras'),
            ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_shelf_snapshots')),
    )
    op.create_index(
        op.f('ix_shelf_snapshots_store_id'), 'shelf_snapshots', ['store_id'], unique=False
    )
    op.create_index(
        op.f('ix_shelf_snapshots_camera_id'), 'shelf_snapshots', ['camera_id'], unique=False
    )
    op.create_index(
        op.f('ix_shelf_snapshots_observed_at'), 'shelf_snapshots', ['observed_at'], unique=False
    )
    op.create_index(
        'ix_shelf_snapshots_store_camera_shelf_observed',
        'shelf_snapshots',
        ['store_id', 'camera_id', 'shelf_code', 'observed_at'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the M30 shelf-snapshot table."""
    op.drop_index(
        'ix_shelf_snapshots_store_camera_shelf_observed', table_name='shelf_snapshots'
    )
    op.drop_index(op.f('ix_shelf_snapshots_observed_at'), table_name='shelf_snapshots')
    op.drop_index(op.f('ix_shelf_snapshots_camera_id'), table_name='shelf_snapshots')
    op.drop_index(op.f('ix_shelf_snapshots_store_id'), table_name='shelf_snapshots')
    op.drop_table('shelf_snapshots')