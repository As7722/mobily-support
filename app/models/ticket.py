from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Ticket(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """
    Core ticket table — partitioned by created_at (year) in PostgreSQL.
    Partition DDL is managed by Alembic migration, not the ORM model.
    """

    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('critical','high','medium','low')",
            name="ck_tickets_priority",
        ),
        CheckConstraint(
            "status IN ('new','open','pending_customer','pending_3rd','resolved','closed','archived')",
            name="ck_tickets_status",
        ),
        CheckConstraint(
            "current_queue IN ('main','specialized','supervisor','manager','internal_tickets')",
            name="ck_tickets_queue",
        ),
        CheckConstraint(
            "channel IN ('portal','email','whatsapp','phone')",
            name="ck_tickets_channel",
        ),
    )

    ticket_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    # Opaque token for public portal URL (/ticket/{token}) — never changes
    public_token: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)

    # ── Submitter ────────────────────────────────────────────────────────────
    submitted_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True
    )
    branch_employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branch_employees.id")
    )
    employee_id: Mapped[Optional[str]] = mapped_column(String(50))
    submitter_name: Mapped[Optional[str]] = mapped_column(String(200))
    submitter_name_ar: Mapped[Optional[str]] = mapped_column(String(150))
    submitter_name_en: Mapped[Optional[str]] = mapped_column(String(150))
    submitter_phone: Mapped[Optional[str]] = mapped_column(String(20))
    submitter_email: Mapped[Optional[str]] = mapped_column(String(255))

    # ── Content ──────────────────────────────────────────────────────────────
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), index=True
    )
    subject: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)

    # ── Queue ────────────────────────────────────────────────────────────────
    current_queue: Mapped[str] = mapped_column(String(30), default="main", index=True)
    sub_queue_dept_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id")
    )

    # ── Assignment ───────────────────────────────────────────────────────────
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    assigned_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))

    # ── Relations ────────────────────────────────────────────────────────────
    parent_ticket_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id")
    )

    # ── Channel ──────────────────────────────────────────────────────────────
    channel: Mapped[str] = mapped_column(String(20), default="portal")
    source_email_uid: Mapped[Optional[str]] = mapped_column(String(255))

    # ── SLA ──────────────────────────────────────────────────────────────────
    sla_policy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sla_policies.id")
    )
    sla_deadline: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True), index=True)
    sla_paused_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    sla_total_paused: Mapped[int] = mapped_column(Integer, default=0)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sla_notified_75: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_notified_90: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_notified_100: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Metrics ──────────────────────────────────────────────────────────────
    first_response_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    total_time_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # ── Automated Time Tracking ───────────────────────────────────────────
    work_time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_opened_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))

    # ── CSAT ─────────────────────────────────────────────────────────────────
    csat_token: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    csat_sent_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    csat_score: Mapped[Optional[float]] = mapped_column(sa.Float)
    csat_comments: Mapped[Optional[str]] = mapped_column(Text)

    # ── Locking (agent collision detection) ──────────────────────────────────
    locked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))

    # ── Dynamic form data ────────────────────────────────────────────────────
    custom_fields: Mapped[Optional[dict]] = mapped_column(
        sa.dialects.postgresql.JSONB, default=dict
    )

    # ── Optimistic locking ───────────────────────────────────────────────────
    version: Mapped[int] = mapped_column(Integer, default=1)

    # ── Relationships ────────────────────────────────────────────────────────
    submitted_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[submitted_by_id])  # noqa: F821
    branch: Mapped[Optional["Branch"]] = relationship("Branch", back_populates="tickets", foreign_keys=[branch_id])  # noqa: F821
    branch_employee: Mapped[Optional["BranchEmployee"]] = relationship("BranchEmployee", foreign_keys=[branch_employee_id])  # noqa: F821
    category: Mapped[Optional["Category"]] = relationship("Category", foreign_keys=[category_id])  # noqa: F821
    assignee: Mapped[Optional["User"]] = relationship("User", foreign_keys=[assigned_to])  # noqa: F821
    locker: Mapped[Optional["User"]] = relationship("User", foreign_keys=[locked_by])  # noqa: F821
    sla_policy: Mapped[Optional["SLAPolicy"]] = relationship("SLAPolicy", foreign_keys=[sla_policy_id])  # noqa: F821
    parent_ticket: Mapped[Optional["Ticket"]] = relationship("Ticket", remote_side="Ticket.id", foreign_keys=[parent_ticket_id])
    timeline: Mapped[list["TicketTimeline"]] = relationship("TicketTimeline", back_populates="ticket", cascade="all, delete-orphan")  # noqa: F821
    attachments: Mapped[list["TicketAttachment"]] = relationship("TicketAttachment", back_populates="ticket")  # noqa: F821
    watchers: Mapped[list["TicketWatcher"]] = relationship("TicketWatcher", back_populates="ticket")  # noqa: F821
    ticket_tags: Mapped[list["TicketTag"]] = relationship("TicketTag", back_populates="ticket")  # noqa: F821
    queue_transfers: Mapped[list["QueueTransfer"]] = relationship("QueueTransfer", back_populates="ticket")  # noqa: F821
    sla_pauses: Mapped[list["SLAPause"]] = relationship("SLAPause", back_populates="ticket")  # noqa: F821
    csat_survey: Mapped[Optional["CSATSurvey"]] = relationship("CSATSurvey", back_populates="ticket", uselist=False)  # noqa: F821
    time_trackings: Mapped[list["TimeTracking"]] = relationship("TimeTracking", back_populates="ticket")  # noqa: F821
    follow_ups: Mapped[list["FollowUp"]] = relationship("FollowUp", back_populates="ticket")  # noqa: F821


__all__ = ["Ticket"]
