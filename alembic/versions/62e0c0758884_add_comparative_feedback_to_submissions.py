"""add comparative_feedback to submissions

Revision ID: 62e0c0758884
Revises: b34fa3d8a582
Create Date: 2026-02-28 21:25:18.450644

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62e0c0758884'
down_revision: Union[str, Sequence[str], None] = 'b34fa3d8a582'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c["name"] for c in insp.get_columns(table)]
    return column in columns


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        if not _has_column('submissions', 'comparative_feedback'):
            batch_op.add_column(sa.Column('comparative_feedback', sa.Text(), nullable=True))
        if _has_column('submissions', 'comparison_feedback'):
            batch_op.drop_column('comparison_feedback')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('comparison_feedback', sa.TEXT(), nullable=True))
        batch_op.drop_column('comparative_feedback')
