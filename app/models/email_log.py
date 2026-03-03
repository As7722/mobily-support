from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class EmailIngestionLog(UUIDPrimaryKeyMixin, Base):
    """
    Tracks every email processed from the IMAP inbox.
    Prevents duplicate ticket creation from the same email.
    """

    __tablename__ = "email_ingestion_log"

    message_uid: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    from_address: Mapped[Optional[str]] = mapped_column(String(255))
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id")
    )
    action: Mapped[Optional[str]] = mapped_column(String(30), index=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    processed_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), index=True
    )


__all__ = ["EmailIngestionLog"]
