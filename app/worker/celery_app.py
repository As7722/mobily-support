from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "mobily_support",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=[
        "app.worker.tasks.sla",
        "app.worker.tasks.notifications",
        "app.worker.tasks.email_ingestion",
        "app.worker.tasks.reports",
        "app.worker.tasks.health",
    ],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone=settings.TIMEZONE,
    enable_utc=True,
    # Task routing to named queues
    task_routes={
        "app.worker.tasks.sla.*": {"queue": "sla"},
        "app.worker.tasks.notifications.*": {"queue": "notifications"},
        "app.worker.tasks.reports.*": {"queue": "reports"},
        "app.worker.tasks.email_ingestion.*": {"queue": "default"},
        "app.worker.tasks.health.*": {"queue": "default"},
    },
    # Result expiry
    result_expires=3600,
    # Beat schedule — periodic tasks
    beat_schedule={
        # SLA breach checker — every minute
        "check-sla-breaches": {
            "task": "check-sla-breaches",
            "schedule": 60.0,
            "options": {"queue": "sla"},
        },
        # Email ingestion (IMAP polling) — every 60 seconds
        "ingest-emails": {
            "task": "email.poll_inbox",
            "schedule": settings.IMAP_POLL_INTERVAL_SECONDS,
            "options": {"queue": "default"},
        },
        # Leaderboard snapshots
        "daily-leaderboard-snapshot": {
            "task": "gamification.daily_leaderboard",
            "schedule": crontab(hour=0, minute=0),
            "options": {"queue": "reports"},
        },
        "weekly-leaderboard-snapshot": {
            "task": "gamification.weekly_leaderboard",
            "schedule": crontab(day_of_week="monday", hour=0, minute=5),
            "options": {"queue": "reports"},
        },
        "monthly-leaderboard-snapshot": {
            "task": "gamification.monthly_leaderboard",
            "schedule": crontab(day_of_month=1, hour=0, minute=10),
            "options": {"queue": "reports"},
        },
        # Scheduled reports — weekly on Sunday 07:00
        "weekly-report": {
            "task": "reports.generate_scheduled",
            "schedule": crontab(day_of_week="sunday", hour=7, minute=0),
            "kwargs": {"period": "weekly"},
            "options": {"queue": "reports"},
        },
        # System health snapshot — every 5 minutes
        "system-health-snapshot": {
            "task": "app.worker.tasks.health.record_system_health",
            "schedule": 300.0,
            "options": {"queue": "default"},
        },
        # Auto-archive tickets closed > 365 days — daily at 01:00
        "auto-archive-old-tickets": {
            "task": "app.worker.tasks.sla.auto_archive_old_tickets",
            "schedule": crontab(hour=1, minute=0),
            "options": {"queue": "sla"},
        },
        # Auto-resolve tickets pending_customer > 48h with no reply — every hour
        "auto-resolve-pending-customer": {
            "task": "auto-resolve-pending-customer",
            "schedule": crontab(minute=0),
            "options": {"queue": "sla"},
        },
        # Monthly employee-of-month auto-selection — 1st of each month at 06:00
        "employee-of-month": {
            "task": "gamification.employee_of_month",
            "schedule": crontab(day_of_month=1, hour=6, minute=0),
            "options": {"queue": "reports"},
        },
        # Theme auto-activation check — every hour
        "theme-auto-activate": {
            "task": "app.worker.tasks.health.auto_activate_themes",
            "schedule": crontab(minute=0),
            "options": {"queue": "default"},
        },
    },
)
