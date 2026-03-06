"""
Audit Service — Enterprise-grade immutable audit trail.
Logs all critical operations for compliance and traceability.
Matches global standards: who, what, when, where, before/after.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

UTC = timezone.utc


async def log(
    db: AsyncSession,
    action: str,
    *,
    actor_id: Optional[uuid.UUID] = None,
    actor_ip: Optional[str] = None,
    actor_role: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[uuid.UUID] = None,
    old_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
    metadata_: Optional[dict[str, Any]] = None,
) -> None:
    """
    Create an immutable audit log entry.
    All critical system operations should call this.
    """
    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_id=actor_id,
        actor_ip=actor_ip,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        metadata_=metadata_,
    ))


def _actor_from_request(request: Any) -> tuple[Optional[uuid.UUID], Optional[str], Optional[str]]:
    """Extract actor_id, actor_ip, actor_role from request. Robust to any payload shape."""
    user = getattr(request.state, "user", None)
    if user is None:
        user = {}
    if not isinstance(user, dict):
        user = {}
    actor_id = None
    sub = user.get("sub")
    if sub is not None:
        try:
            actor_id = uuid.UUID(str(sub).strip())
        except (ValueError, TypeError, AttributeError):
            pass
    actor_ip = None
    if request and hasattr(request, "client") and request.client:
        actor_ip = getattr(request.client, "host", None) or None
    actor_role = user.get("role")
    if actor_role is not None and not isinstance(actor_role, str):
        actor_role = str(actor_role)
    return actor_id, actor_ip, actor_role


async def log_from_request(
    db: AsyncSession,
    request: Any,
    action: str,
    *,
    resource_type: Optional[str] = None,
    resource_id: Optional[uuid.UUID] = None,
    old_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
    metadata_: Optional[dict[str, Any]] = None,
) -> None:
    """Log audit entry with actor info from request."""
    actor_id, actor_ip, actor_role = _actor_from_request(request)
    await log(
        db,
        action,
        actor_id=actor_id,
        actor_ip=actor_ip,
        actor_role=actor_role,
        resource_type=resource_type,
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        metadata_=metadata_,
    )


# ── Action constants (for consistency) ────────────────────────────────────────
class AuditAction:
    # Auth
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    LOGIN_FAILED = "auth.login_failed"
    PASSWORD_RESET = "auth.password_reset"
    TWO_FA_ENABLED = "auth.2fa_enabled"
    TWO_FA_DISABLED = "auth.2fa_disabled"

    # Users
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DELETE = "user.delete"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_DEPARTMENT_CHANGED = "user.department_changed"
    USER_DEPARTMENTS_CHANGED = "user.departments_changed"
    USER_TOGGLE_ACTIVE = "user.toggle_active"
    USER_FORCE_LOGOUT = "user.force_logout"
    USER_PASSWORD_RESET = "user.password_reset"

    # Tickets
    TICKET_CREATE = "ticket.create"
    TICKET_UPDATE = "ticket.update"
    TICKET_ASSIGN = "ticket.assign"
    TICKET_STATUS_CHANGE = "ticket.status_change"
    TICKET_RESOLVE = "ticket.resolve"
    TICKET_CLOSE = "ticket.close"
    TICKET_ESCALATE = "ticket.escalate"
    TICKET_DEESCALATE = "ticket.deescalate"
    TICKET_MERGE = "ticket.merge"
    TICKET_SPLIT = "ticket.split"
    TICKET_COMMENT = "ticket.comment"
    TICKET_ARCHIVE = "ticket.archive"

    # SLA
    SLA_POLICY_CREATE = "sla.create"
    SLA_POLICY_UPDATE = "sla.update"
    SLA_POLICY_DELETE = "sla.delete"

    # Automation
    AUTOMATION_CREATE = "automation.create"
    AUTOMATION_UPDATE = "automation.update"
    AUTOMATION_DELETE = "automation.delete"

    # Notifications
    NOTIFICATION_TOGGLE = "notification.toggle"
    NOTIFICATION_SOUND_TOGGLE = "notification.sound_toggle"

    # Departments
    DEPARTMENT_CREATE = "department.create"
    DEPARTMENT_UPDATE = "department.update"
    DEPARTMENT_TOGGLE = "department.toggle"
    DEPARTMENT_FIELDS_UPDATE = "department.fields_update"

    # Permissions
    PERMISSION_TOGGLE = "permission.toggle"
    PERMISSION_RESET = "permission.reset"

    # Form / KB
    FORM_VERSION_CREATE = "form_version.create"
    FORM_VERSION_ACTIVATE = "form_version.activate"
    KB_ARTICLE_CREATE = "kb.create"
    KB_ARTICLE_UPDATE = "kb.update"
    KB_ARTICLE_DELETE = "kb.delete"

    # Reports
    REPORT_SCHEDULED = "report.scheduled"
    REPORT_SENT = "report.sent"
    REPORT_EXPORT = "report.export"

    # Broadcast
    BROADCAST_SENT = "broadcast.sent"

    # Export (audit trail of data exports)
    EXPORT_TICKETS = "export.tickets"
    EXPORT_AGENTS = "export.agents"
    EXPORT_AUDIT = "export.audit"
    EXPORT_CALL_LOGS = "export.call_logs"

    # Portal (external public portal)
    PORTAL_TRACK = "portal.track"
    PORTAL_VIEW = "portal.view"
    PORTAL_REPLY = "portal.reply"
    PORTAL_CSAT_SUBMIT = "portal.csat_submit"
    PORTAL_REGISTER_EMPLOYEE = "portal.register_employee"
