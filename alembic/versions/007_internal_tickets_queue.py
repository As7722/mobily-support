"""007 — add internal_tickets queue type + CS-INT counter seed

Revision ID: 007
Revises: 006
Create Date: 2026-02-27
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Drop old CHECK constraint and recreate with internal_tickets
    conn.execute(sa.text("""
        ALTER TABLE tickets
        DROP CONSTRAINT IF EXISTS ck_tickets_queue
    """))
    conn.execute(sa.text("""
        ALTER TABLE tickets
        ADD CONSTRAINT ck_tickets_queue
        CHECK (current_queue IN ('main','specialized','supervisor','manager','internal_tickets'))
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_queue"))
    conn.execute(sa.text("""
        ALTER TABLE tickets
        ADD CONSTRAINT ck_tickets_queue
        CHECK (current_queue IN ('main','specialized','supervisor','manager'))
    """))
