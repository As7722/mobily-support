from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class TicketWatcher(Base):
    """Many-to-many: users watching a ticket for notifications."""

    __tablename__ = "ticket_watchers"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="watchers")  # noqa: F821
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])  # noqa: F821


class TicketTag(Base):
    """Many-to-many: tags on a ticket."""

    __tablename__ = "ticket_tags"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="ticket_tags")  # noqa: F821
    tag: Mapped["Tag"] = relationship("Tag", foreign_keys=[tag_id])  # noqa: F821


class QueueTransfer(UUIDPrimaryKeyMixin, Base):
    """Full history of queue movements for a ticket. Mandatory reason field."""

    __tablename__ = "queue_transfers"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False, index=True
    )
    from_queue: Mapped[Optional[str]] = mapped_column(String(30))
    to_queue: Mapped[Optional[str]] = mapped_column(String(30))
    from_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    to_agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    transferred_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="queue_transfers")  # noqa: F821
    from_agent: Mapped[Optional["User"]] = relationship("User", foreign_keys=[from_agent_id])  # noqa: F821
    to_agent: Mapped[Optional["User"]] = relationship("User", foreign_keys=[to_agent_id])  # noqa: F821
    transferred_by_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[transferred_by])  # noqa: F821


__all__ = ["TicketWatcher", "TicketTag", "QueueTransfer"]
