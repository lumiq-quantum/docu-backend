""""add_chat_session_id_to_project"

Revision ID: e422a4bb40e6
Revises: 6f6fe249a03d
Create Date: 2025-05-28 14:45:54.149762

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e422a4bb40e6'
down_revision: Union[str, None] = '6f6fe249a03d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
