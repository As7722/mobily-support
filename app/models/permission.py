from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class RolePermission(UUIDPrimaryKeyMixin, Base):
    """
    Dynamic RBAC: each row grants/denies a permission_key for a role.
    Cached in Redis for 15 minutes (key: perms:{role}).
    """

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role", "permission_key", name="uq_role_permission"),
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    permission_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    is_granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


__all__ = ["RolePermission"]
