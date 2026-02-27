"""merge multiple heads

Revision ID: cd6a7beeb7c9
Revises: 36e56e5995da, 5beadeb24e13
Create Date: 2026-02-27 22:22:33.650689

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd6a7beeb7c9'
down_revision: Union[str, Sequence[str], None] = ('36e56e5995da', '5beadeb24e13')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
