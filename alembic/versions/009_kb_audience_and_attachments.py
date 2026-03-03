"""009 — split KB audience and add attachments

Revision ID: 009
Revises: 008
Create Date: 2026-03-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_articles",
        sa.Column("audience", sa.String(length=20), nullable=False, server_default="internal"),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("attachment_file_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("attachment_storage_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("attachment_mime_type", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("attachment_size_bytes", sa.Integer(), nullable=True),
    )
    op.create_index(op.f("ix_knowledge_articles_audience"), "knowledge_articles", ["audience"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_articles_audience"), table_name="knowledge_articles")
    op.drop_column("knowledge_articles", "attachment_size_bytes")
    op.drop_column("knowledge_articles", "attachment_mime_type")
    op.drop_column("knowledge_articles", "attachment_storage_key")
    op.drop_column("knowledge_articles", "attachment_file_name")
    op.drop_column("knowledge_articles", "audience")
