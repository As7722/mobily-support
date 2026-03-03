"""Migrate ticket numbers from TKT-YYYYMMDD-NNNN to CSTS-NNN format.

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT id, ticket_number FROM tickets "
            "WHERE ticket_number LIKE 'TKT-%' "
            "ORDER BY created_at ASC"
        )
    ).fetchall()

    for idx, (tid, _old_num) in enumerate(rows, start=1):
        new_num = f"CSTS-{idx:03d}"
        conn.execute(
            sa.text("UPDATE tickets SET ticket_number = :num WHERE id = :id"),
            {"num": new_num, "id": tid},
        )


def downgrade() -> None:
    pass
