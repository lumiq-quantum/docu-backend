""""add_generated_form_html_to_page"

Revision ID: 6f6fe249a03d
Revises: 5ab9971d0dd3
Create Date: 2025-05-28 03:57:35.054877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f6fe249a03d'
down_revision: Union[str, None] = '5ab9971d0dd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
