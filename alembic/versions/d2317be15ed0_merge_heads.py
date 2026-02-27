"""merge heads

Revision ID: d2317be15ed0
Revises: 36e56e5995da, 5beadeb24e13
Create Date: 2026-02-27 22:16:03.316001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2317be15ed0'
down_revision: Union[str, Sequence[str], None] = ('36e56e5995da', '5beadeb24e13')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
