from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Theme(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Seasonal/campaign themes with auto-activation scheduling."""

    __tablename__ = "themes"

    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    description_ar: Mapped[Optional[str]] = mapped_column(Text)
    description_en: Mapped[Optional[str]] = mapped_column(Text)
    icon_emoji: Mapped[Optional[str]] = mapped_column(String(10))
    primary_color: Mapped[str] = mapped_column(String(7), nullable=False)
    secondary_color: Mapped[str] = mapped_column(String(7), nullable=False)
    background_color: Mapped[Optional[str]] = mapped_column(String(7))
    logo_s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    bg_pattern_s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    bg_opacity: Mapped[float] = mapped_column(Float, default=0.2)
    welcome_message_ar: Mapped[Optional[str]] = mapped_column(String(200))
    welcome_message_en: Mapped[Optional[str]] = mapped_column(String(200))
    custom_css: Mapped[Optional[str]] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    auto_activate: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class BrandingConfig(UUIDPrimaryKeyMixin, Base):
    """Global branding settings (logo, colors, fonts). Single live row."""

    __tablename__ = "branding_config"

    logo_s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    favicon_s3_key: Mapped[Optional[str]] = mapped_column(String(500))
    primary_color: Mapped[str] = mapped_column(String(7), default="#0066CC")
    secondary_color: Mapped[str] = mapped_column(String(7), default="#C8215D")
    background_color: Mapped[str] = mapped_column(String(7), default="#FFFFFF")
    text_color: Mapped[str] = mapped_column(String(7), default="#1A1A1A")
    font_arabic: Mapped[str] = mapped_column(String(100), default="Tajawal")
    font_latin: Mapped[str] = mapped_column(String(100), default="Inter")
    custom_css: Mapped[Optional[str]] = mapped_column(Text)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


__all__ = ["Theme", "BrandingConfig"]
