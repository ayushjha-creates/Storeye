"""add product ai_classes mapping

Revision ID: b7f3d11e4a59
Revises: acf54c2aa5f9
Create Date: 2026-09-07 08:10:00.000000

The `ai_classes` column stores an explicit, configurable mapping between Edge
AI class names (e.g. "Complan") and Storeye products. Without it the AI never
guesses a product association.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7f3d11e4a59'
down_revision: Union[str, Sequence[str], None] = 'acf54c2aa5f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'products',
        sa.Column(
            'ai_classes',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('products', 'ai_classes')