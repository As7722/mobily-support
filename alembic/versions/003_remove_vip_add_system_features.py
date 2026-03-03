"""Remove VIP, no VIP features in the system.

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("branches", "is_vip")


def downgrade() -> None:
    op.add_column("branches", sa.Column("is_vip", sa.Boolean(), server_default="false"))
