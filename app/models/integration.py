from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class IntegrationConfig(UUIDPrimaryKeyMixin, Base):
    """
    AES-256 encrypted key=value store for external integrations
    (SMTP, IMAP, Twilio, S3). Only admins can read/write.
    """

    __tablename__ = "integration_configs"

    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    value_enc: Mapped[Optional[str]] = mapped_column(Text, comment="AES-256 encrypted value")
    is_test_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class APIKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """External API keys for webhooks / integrations."""

    __tablename__ = "api_keys"

    name_ar: Mapped[Optional[str]] = mapped_column(String(100))
    name_en: Mapped[Optional[str]] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_4: Mapped[Optional[str]] = mapped_column(String(4))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


__all__ = ["IntegrationConfig", "APIKey"]
