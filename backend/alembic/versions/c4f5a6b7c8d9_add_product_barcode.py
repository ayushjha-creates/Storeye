"""add products.barcode

Revision ID: c4f5a6b7c8d9
Revises: d9e4a30f8b21
Create Date: 2026-09-08 11:00:00.000000

The `barcode` column stores the machine-readable product identifier (GTIN,
EAN/UPC, Code-39 SKU/number, ...) printed on the package. Smart Batch
Receiving decodes it from a close-up package photo to resolve the LOCAL
Product catalog entry. A barcode never carries batch/expiry/MRP data — those
are printed on the pack and read with close-up OCR.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd9e4a30f8b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'products',
        sa.Column('barcode', sa.String(length=64), nullable=True),
    )
    op.create_index(
        'ix_products_barcode', 'products', ['barcode'], unique=False
    )
    op.create_unique_constraint(
        'uq_products_store_barcode', 'products', ['store_id', 'barcode']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_products_store_barcode', 'products', type_='unique')
    op.drop_index('ix_products_barcode', table_name='products')
    op.drop_column('products', 'barcode')