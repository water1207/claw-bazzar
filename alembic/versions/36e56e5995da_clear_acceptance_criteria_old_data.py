"""clear_acceptance_criteria_old_data

Revision ID: 36e56e5995da
Revises: bb58022f4efe
Create Date: 2026-02-27 18:21:06.769378

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36e56e5995da'
down_revision: Union[str, Sequence[str], None] = 'bb58022f4efe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE tasks SET acceptance_criteria = NULL")


def downgrade() -> None:
    pass  # 不可逆
