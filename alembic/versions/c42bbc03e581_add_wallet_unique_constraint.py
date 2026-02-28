"""add_wallet_unique_constraint

Revision ID: c42bbc03e581
Revises: 62e0c0758884
Create Date: 2026-03-01 02:29:05.364911

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'c42bbc03e581'
down_revision: Union[str, Sequence[str], None] = '62e0c0758884'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: deduplicate wallet entries, then add unique constraint."""
    conn = op.get_bind()

    # Step 1: Normalize all wallet values to lowercase
    conn.execute(text("UPDATE users SET wallet = lower(wallet)"))

    # Step 2: Find duplicates (same wallet, different roles) and merge into 'both'
    duplicates = conn.execute(text(
        "SELECT wallet FROM users GROUP BY wallet HAVING COUNT(*) > 1"
    )).fetchall()

    for row in duplicates:
        wallet = row[0]
        users = conn.execute(text(
            "SELECT id, role FROM users WHERE wallet = :w ORDER BY created_at ASC"
        ), {"w": wallet}).fetchall()

        keep_id = users[0][0]
        roles = {u[1] for u in users}

        # If multiple roles exist, upgrade kept user to 'both'
        if len(roles) > 1:
            conn.execute(text(
                "UPDATE users SET role = 'both' WHERE id = :id"
            ), {"id": keep_id})

        # Delete duplicate users, reassigning their relations first
        for u in users[1:]:
            dup_id = u[0]
            conn.execute(text(
                "UPDATE submissions SET worker_id = :keep WHERE worker_id = :dup"
            ), {"keep": keep_id, "dup": dup_id})
            conn.execute(text(
                "UPDATE tasks SET publisher_id = :keep WHERE publisher_id = :dup"
            ), {"keep": keep_id, "dup": dup_id})
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": dup_id})

    # Step 3: Add unique constraint
    # batch_alter_table handles both PostgreSQL (direct ALTER) and SQLite (table rebuild)
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_unique_constraint("uq_users_wallet", ["wallet"])


def downgrade() -> None:
    """Downgrade schema: remove unique constraint on wallet."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_wallet", type_="unique")
