"""010 — add custom_fields JSONB column to tickets

Revision ID: 010
Revises: 009
Create Date: 2026-03-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("custom_fields", JSONB, nullable=True, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("tickets", "custom_fields")
