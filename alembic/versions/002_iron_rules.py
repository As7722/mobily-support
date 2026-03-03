"""Iron Rules — remove on_hold, add specialized queue, automated time tracking columns

Revision ID: 002
Revises: 001
Create Date: 2026-02-27
"""
from __future__ import annotations

from alembic import op

revision: str = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Add automated time tracking columns ─────────────────────────────
    op.execute("""
    ALTER TABLE tickets
        ADD COLUMN IF NOT EXISTS work_time_seconds INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMPTZ
    """)

    # ── 2. Migrate on_hold tickets to open before constraint change ────────
    op.execute("UPDATE tickets SET status = 'open' WHERE status = 'on_hold'")

    # ── 3. Drop and recreate status constraint (remove on_hold) ────────────
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_status")
    op.execute("""
    ALTER TABLE tickets ADD CONSTRAINT ck_tickets_status
        CHECK (status IN ('new','open','pending_customer','pending_3rd','resolved','closed','archived'))
    """)

    # ── 4. Drop and recreate queue constraint (add specialized) ────────────
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_queue")
    op.execute("""
    ALTER TABLE tickets ADD CONSTRAINT ck_tickets_queue
        CHECK (current_queue IN ('main','specialized','supervisor','manager'))
    """)

    # ── 5. Set last_opened_at for currently-open tickets ───────────────────
    op.execute("""
    UPDATE tickets SET last_opened_at = updated_at
    WHERE status = 'open' AND last_opened_at IS NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_status")
    op.execute("""
    ALTER TABLE tickets ADD CONSTRAINT ck_tickets_status
        CHECK (status IN ('new','open','pending_customer','pending_3rd','on_hold','resolved','closed','archived'))
    """)

    op.execute("ALTER TABLE tickets DROP CONSTRAINT IF EXISTS ck_tickets_queue")
    op.execute("""
    ALTER TABLE tickets ADD CONSTRAINT ck_tickets_queue
        CHECK (current_queue IN ('main','supervisor','manager'))
    """)

    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS work_time_seconds")
    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS last_opened_at")
