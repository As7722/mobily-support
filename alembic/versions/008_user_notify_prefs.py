"""008 — add notification preference columns to users

Revision ID: 008
Revises: 007
Create Date: 2026-02-27
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "notify_email_assign", sa.Boolean(), nullable=False, server_default="true"
    ))
    op.add_column("users", sa.Column(
        "notify_sms_sla", sa.Boolean(), nullable=False, server_default="true"
    ))
    op.add_column("users", sa.Column(
        "notify_email_daily", sa.Boolean(), nullable=False, server_default="false"
    ))


def downgrade() -> None:
    op.drop_column("users", "notify_email_daily")
    op.drop_column("users", "notify_sms_sla")
    op.drop_column("users", "notify_email_assign")
