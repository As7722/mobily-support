# ─────────────────────────────────────────────────────────────────────────────
# Import ALL models here so that:
#   1. SQLAlchemy can resolve all relationship() string references
#   2. Alembic autogenerate sees every table in Base.metadata
#   3. app/main.py only needs: from app.models import *
# ─────────────────────────────────────────────────────────────────────────────

from app.models.department import Department, UserDepartment
from app.models.user import User
from app.models.permission import RolePermission
from app.models.branch import Branch, BranchEmployee
from app.models.category import Category, Tag
from app.models.sla import SLAPolicy, SLAPause
from app.models.ticket import Ticket
from app.models.ticket_timeline import TicketTimeline, TicketAttachment
from app.models.ticket_assoc import TicketWatcher, TicketTag, QueueTransfer
from app.models.csat import CSATSurvey
from app.models.call_log import CallLog
from app.models.knowledge import KnowledgeArticle, CannedResponse
from app.models.system import SystemAlert, SystemStatus, Incident, ScheduledMaintenance
from app.models.automation import AutomationRule, AutomationExecutionLog
from app.models.form import FormVersion, FormFieldDefinition
from app.models.gamification import GamificationBadge, UserBadge, LeaderboardSnapshot, EmployeeOfMonth
from app.models.theme import Theme, BrandingConfig
from app.models.integration import IntegrationConfig, APIKey
from app.models.audit import AuditLog
from app.models.user_session import UserSession
from app.models.feature_flag import FeatureFlag
from app.models.notification import Notification, NotificationRule
from app.models.schedule import AgentSchedule, ShiftSwap, LeaveRequest, Holiday
from app.models.report import ScheduledReport
from app.models.tracking import TimeTracking, FollowUp
from app.models.ip_whitelist import IPWhitelist
from app.models.email_log import EmailIngestionLog
from app.models.health import SystemHealthSnapshot

__all__ = [
    # Auth / Users
    "Department",
    "UserDepartment",
    "User",
    "RolePermission",
    "UserSession",
    # Branches
    "Branch",
    "BranchEmployee",
    # Taxonomy
    "Category",
    "Tag",
    # SLA
    "SLAPolicy",
    "SLAPause",
    # Tickets (core)
    "Ticket",
    "TicketTimeline",
    "TicketAttachment",
    "TicketWatcher",
    "TicketTag",
    "QueueTransfer",
    # Customer-facing
    "CSATSurvey",
    "CallLog",
    # Knowledge
    "KnowledgeArticle",
    "CannedResponse",
    # System / Status
    "SystemAlert",
    "SystemStatus",
    "Incident",
    "ScheduledMaintenance",
    # Automation / Forms
    "AutomationRule",
    "AutomationExecutionLog",
    "FormVersion",
    "FormFieldDefinition",
    # Gamification
    "GamificationBadge",
    "UserBadge",
    "LeaderboardSnapshot",
    "EmployeeOfMonth",
    # Theme / Branding
    "Theme",
    "BrandingConfig",
    # Integration / API
    "IntegrationConfig",
    "APIKey",
    # Audit
    "AuditLog",
    # Flags / Notifications / Scheduling / Reports
    "FeatureFlag",
    "Notification",
    "NotificationRule",
    "AgentSchedule",
    "ShiftSwap",
    "LeaveRequest",
    "Holiday",
    "ScheduledReport",
    "TimeTracking",
    "FollowUp",
    # Security
    "IPWhitelist",
    # Misc
    "EmailIngestionLog",
    "SystemHealthSnapshot",
]
