from __future__ import annotations

from app.worker.celery_app import celery_app


@celery_app.task(name="app.worker.tasks.health.record_system_health", bind=True)
def record_system_health(self) -> dict:
    """Snapshot DB, Redis, Celery, disk, and CPU metrics to system_health_snapshots."""
    # TODO: implement in Phase 2
    return {"status": "ok"}


@celery_app.task(name="app.worker.tasks.health.auto_activate_themes", bind=True)
def auto_activate_themes(self) -> dict:
    """Check themes.starts_at / ends_at and toggle is_active accordingly."""
    # TODO: implement in Phase 2
    return {"status": "ok"}
