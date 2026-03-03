"""
Server-Sent Events — live push to browsers.
Streams:
  /api/sse/alerts        — system alert banner (all pages)
  /api/sse/queue         — employee smart queue (30-s refresh signal)
  /api/sse/workload      — supervisor workload (30-s refresh signal)
  /api/sse/ticket/{id}   — agent collision detection on ticket detail
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis

router = APIRouter()
UTC = timezone.utc


async def _event(data: str, event: str = "message") -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def _keepalive_loop(
    interval: int = 25,
) -> AsyncGenerator[str, None]:
    """Yield keepalive comments so proxy servers don't close the connection."""
    while True:
        yield ": ping\n\n"
        await asyncio.sleep(interval)


# ── System alert banner ────────────────────────────────────────────────────────

@router.get("/api/sse/alerts", include_in_schema=False)
async def sse_alerts(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    async def _generate() -> AsyncGenerator[str, None]:
        from sqlalchemy import select, or_
        from app.models.system import SystemAlert

        last_check = datetime.now(tz=UTC)
        while True:
            if await request.is_disconnected():
                break
            now = datetime.now(tz=UTC)
            result = await db.execute(
                select(SystemAlert).where(
                    SystemAlert.is_active.is_(True),
                    SystemAlert.starts_at <= now,
                    or_(SystemAlert.ends_at.is_(None), SystemAlert.ends_at >= now),
                ).order_by(SystemAlert.severity.desc()).limit(3)
            )
            alerts = result.scalars().all()
            data = json.dumps([
                {
                    "id": str(a.id),
                    "severity": a.severity,
                    "message_ar": a.message_ar,
                    "message_en": a.message_en,
                }
                for a in alerts
            ])
            yield await _event(data, "alerts")
            await asyncio.sleep(30)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Queue refresh signal ───────────────────────────────────────────────────────

@router.get("/api/sse/queue", include_in_schema=False)
async def sse_queue(request: Request) -> StreamingResponse:
    async def _generate() -> AsyncGenerator[str, None]:
        while True:
            if await request.is_disconnected():
                break
            yield await _event(json.dumps({"refresh": True}), "queue_refresh")
            await asyncio.sleep(30)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Workload refresh signal ────────────────────────────────────────────────────

@router.get("/api/sse/workload", include_in_schema=False)
async def sse_workload(request: Request) -> StreamingResponse:
    async def _generate() -> AsyncGenerator[str, None]:
        while True:
            if await request.is_disconnected():
                break
            yield await _event(json.dumps({"refresh": True}), "workload_refresh")
            await asyncio.sleep(30)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Agent collision detection on ticket detail ────────────────────────────────

@router.get("/api/sse/ticket/{ticket_id}", include_in_schema=False)
async def sse_ticket_viewers(
    ticket_id: str,
    request: Request,
    redis=Depends(get_redis),
) -> StreamingResponse:
    """
    Announce the current viewer to other agents looking at the same ticket.
    Uses a Redis set key: viewers:{ticket_id}
    """
    viewer_key = f"viewers:{ticket_id}"
    agent_payload = getattr(request.state, "user", None) or {}
    agent_id  = str(agent_payload.get("sub", ""))
    agent_name = agent_payload.get("full_name_ar", agent_payload.get("username", "?"))

    async def _generate() -> AsyncGenerator[str, None]:
        try:
            # Register this viewer
            if agent_id:
                await redis.setex(f"viewer:{ticket_id}:{agent_id}", 35, agent_name)
                await redis.sadd(viewer_key, agent_id)
                await redis.expire(viewer_key, 35)

            while True:
                if await request.is_disconnected():
                    break

                # Collect active viewers (decode_responses=True → already strings)
                viewer_ids: list[str] = list(await redis.smembers(viewer_key))
                viewers = []
                for vid in viewer_ids:
                    name = await redis.get(f"viewer:{ticket_id}:{vid}")
                    if name:
                        viewers.append({"id": vid, "name": name})
                    else:
                        await redis.srem(viewer_key, vid)

                # Refresh TTL for our entry
                if agent_id:
                    await redis.setex(f"viewer:{ticket_id}:{agent_id}", 35, agent_name)

                others = [v for v in viewers if v["id"] != agent_id]
                yield await _event(json.dumps({"viewers": others}), "viewers")
                await asyncio.sleep(15)
        finally:
            if agent_id:
                await redis.srem(viewer_key, agent_id)
                await redis.delete(f"viewer:{ticket_id}:{agent_id}")

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── System status page refresh ────────────────────────────────────────────────

@router.get("/api/sse/status", include_in_schema=False)
async def sse_status(request: Request) -> StreamingResponse:
    async def _generate() -> AsyncGenerator[str, None]:
        while True:
            if await request.is_disconnected():
                break
            yield await _event(json.dumps({"ts": datetime.now(tz=UTC).isoformat()}), "status_update")
            await asyncio.sleep(60)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
