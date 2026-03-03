from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class SystemHealthSnapshot(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "system_health_snapshots"

    db_response_ms: Mapped[Optional[int]] = mapped_column(Integer)
    redis_ms: Mapped[Optional[int]] = mapped_column(Integer)
    celery_workers: Mapped[Optional[int]] = mapped_column(Integer)
    disk_usage_pct: Mapped[Optional[float]] = mapped_column(Float)
    memory_usage_pct: Mapped[Optional[float]] = mapped_column(Float)
    cpu_usage_pct: Mapped[Optional[float]] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=sa.func.now(),
        index=True,
    )


__all__ = ["SystemHealthSnapshot"]
