from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class TicketTimeline(UUIDPrimaryKeyMixin, Base):
    """
    Immutable event log for a ticket. Never updated — only appended.
    is_public=False means internal note (not visible on /ticket/{token} page).
    """

    __tablename__ = "ticket_timeline"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    actor_type: Mapped[Optional[str]] = mapped_column(String(20))
    content_ar: Mapped[Optional[str]] = mapped_column(Text)
    content_en: Mapped[Optional[str]] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), index=True
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="timeline")  # noqa: F821
    actor: Mapped[Optional["User"]] = relationship("User", foreign_keys=[actor_id])  # noqa: F821
    attachments: Mapped[list["TicketAttachment"]] = relationship(  # noqa: F821
        "TicketAttachment", back_populates="timeline_entry"
    )


class TicketAttachment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ticket_attachments"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False, index=True
    )
    timeline_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_timeline.id")
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    s3_bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    virus_scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    virus_clean: Mapped[Optional[bool]] = mapped_column(Boolean)
    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="attachments")  # noqa: F821
    timeline_entry: Mapped[Optional["TicketTimeline"]] = relationship(
        "TicketTimeline", back_populates="attachments"
    )


__all__ = ["TicketTimeline", "TicketAttachment"]
