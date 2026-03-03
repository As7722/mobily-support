from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class CSATSurvey(UUIDPrimaryKeyMixin, Base):
    """
    Customer Satisfaction survey sent after ticket resolution.
    token is single-use and expires after CSAT_TOKEN_EXPIRY_DAYS.
    """

    __tablename__ = "csat_surveys"
    __table_args__ = (
        CheckConstraint("rating_overall BETWEEN 1 AND 5", name="ck_csat_overall"),
        CheckConstraint("rating_speed BETWEEN 1 AND 5", name="ck_csat_speed"),
        CheckConstraint("rating_professionalism BETWEEN 1 AND 5", name="ck_csat_prof"),
        CheckConstraint("rating_clarity BETWEEN 1 AND 5", name="ck_csat_clarity"),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    rating_overall: Mapped[Optional[int]] = mapped_column(SmallInteger)
    rating_speed: Mapped[Optional[int]] = mapped_column(SmallInteger)
    rating_professionalism: Mapped[Optional[int]] = mapped_column(SmallInteger)
    rating_clarity: Mapped[Optional[int]] = mapped_column(SmallInteger)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    token_expires_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), server_default=sa.func.now()
    )

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="csat_survey")  # noqa: F821
    agent: Mapped[Optional["User"]] = relationship("User", foreign_keys=[agent_id])  # noqa: F821


__all__ = ["CSATSurvey"]
