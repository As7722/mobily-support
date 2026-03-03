"""006 call log enhancements — caller_user_id + reason_data

Revision ID: 006
Revises: 005
Create Date: 2026-02-27
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        ALTER TABLE call_logs
        ADD COLUMN IF NOT EXISTS caller_user_id UUID REFERENCES users(id),
        ADD COLUMN IF NOT EXISTS reason_data    JSONB
    """))


def downgrade() -> None:
    pass
