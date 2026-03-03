from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import SoftDeleteMixin, UUIDPrimaryKeyMixin


class IPWhitelist(UUIDPrimaryKeyMixin, SoftDeleteMixin, Base):
    """Admin-managed IP CIDR ranges allowed to access the system."""

    __tablename__ = "ip_whitelist"

    cidr: Mapped[str] = mapped_column(INET, nullable=False)
    label_ar: Mapped[Optional[str]] = mapped_column(String(100))
    label_en: Mapped[Optional[str]] = mapped_column(String(100))
    added_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )


__all__ = ["IPWhitelist"]
