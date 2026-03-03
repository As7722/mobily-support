from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Submission ──────────────────────────────────────────────────────────────

class TicketSubmitForm(BaseModel):
    """Parsed from multipart/form-data by the portal submission endpoint."""
    submitter_name: str = Field(..., min_length=1, max_length=200)
    submitter_phone: str = Field(..., min_length=1, max_length=30)
    submitter_email: Optional[str] = None
    employee_id: Optional[str] = None
    branch_id: Optional[uuid.UUID] = None
    category_id: Optional[uuid.UUID] = None
    subcategory_id: Optional[uuid.UUID] = None
    priority: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    channel: str = Field(default="portal", pattern="^(portal|phone|email|whatsapp)$")
    subject: Optional[str] = Field(default=None, max_length=500)
    description: str = Field(..., min_length=5, max_length=10_000)


class TicketSubmitResponse(BaseModel):
    ticket_number: str
    ticket_id: str
    sla_deadline: Optional[datetime] = None
    message: str = "ok"


# ── Customer reply ──────────────────────────────────────────────────────────

class CustomerReplyRequest(BaseModel):
    reply: str = Field(..., min_length=1, max_length=5_000)


# ── CSAT ─────────────────────────────────────────────────────────────────────

class CSATSubmitForm(BaseModel):
    rating_overall: int = Field(..., ge=1, le=5)
    rating_speed: Optional[int] = Field(default=None, ge=1, le=5)
    rating_professionalism: Optional[int] = Field(default=None, ge=1, le=5)
    rating_clarity: Optional[int] = Field(default=None, ge=1, le=5)
    comments: Optional[str] = Field(default=None, max_length=2_000)


# ── Track response ───────────────────────────────────────────────────────────

class TimelineEventOut(BaseModel):
    id: str
    event_type: str
    content: str
    created_at_label: str
    actor_type: str


class TicketTrackResponse(BaseModel):
    """Iron Rule #3: No priority, no assigned_to, no timeline for public view."""
    found: bool
    ticket_number: Optional[str] = None
    token: Optional[str] = None
    subject: Optional[str] = None
    status: Optional[str] = None
    status_label: Optional[str] = None
    replies: list[TimelineEventOut] = []


class TicketPublicView(BaseModel):
    """Strict public view — only status + public replies."""
    ticket_number: str
    subject: Optional[str] = None
    status: str
    status_label: str
    replies: list[TimelineEventOut] = []
