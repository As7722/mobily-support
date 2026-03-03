"""011 — user_departments many-to-many + portal_fields on departments

Revision ID: 011
Revises: 010
Create Date: 2026-03-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_departments",
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("department_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id"), primary_key=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "departments",
        sa.Column("portal_fields", JSONB, nullable=True, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("departments", "portal_fields")
    op.drop_table("user_departments")
