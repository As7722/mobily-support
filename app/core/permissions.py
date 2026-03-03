from __future__ import annotations

from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.i18n import t

# ─── Hardcoded absolute denials ───────────────────────────────────────────────
# These are NEVER granted, regardless of what the role_permissions table says.
HARDCODED_DENIED: frozenset[str] = frozenset({
    "audit_log.delete",
    "admin_root.disable",
})

_PERM_CACHE_TTL = 900  # 15 minutes


def _perm_cache_key(role: str) -> str:
    return f"perms:{role}"


# ─── Core check function ──────────────────────────────────────────────────────

async def check_permission(
    user_id: UUID,
    user_role: str,
    permission_key: str,
    redis: aioredis.Redis,
    db: AsyncSession,
) -> bool:
    """
    Returns True if user_role is granted permission_key.

    Resolution order:
      1. Hardcoded deny (always False)
      2. Admin role (always True except hardcoded denials)
      3. Redis cache hit (set: perms:{role})
      4. DB lookup → cache result
    """
    # 1. Hardcoded absolute denial
    if permission_key in HARDCODED_DENIED:
        return False

    # 2. Admin bypass
    if user_role == "admin":
        return True

    # 3. Redis cache  (decode_responses=True → members are str, not bytes)
    cache_key = _perm_cache_key(user_role)
    cached: set[str] = await redis.smembers(cache_key)
    if cached:
        return permission_key in cached

    # 4. DB lookup
    from app.models.permission import RolePermission

    result = await db.execute(
        select(RolePermission.permission_key)
        .where(
            RolePermission.role == user_role,
            RolePermission.is_granted.is_(True),
        )
    )
    granted: set[str] = {row[0] for row in result.fetchall()}

    # Populate Redis cache
    if granted:
        await redis.sadd(cache_key, *granted)
        await redis.expire(cache_key, _PERM_CACHE_TTL)

    return permission_key in granted


async def invalidate_permission_cache(role: str, redis: aioredis.Redis) -> None:
    """Call after any role_permissions update to flush the cache for that role."""
    await redis.delete(_perm_cache_key(role))


# ─── FastAPI dependency factory ───────────────────────────────────────────────

def require_permission(permission_key: str):
    """
    Usage:
        @router.post("/tickets/{id}/merge")
        async def merge_tickets(
            id: UUID,
            user = Depends(require_permission("tickets.merge")),
        ): ...
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),
        redis: aioredis.Redis = Depends(get_redis),
    ) -> dict:
        lang = getattr(request.state, "lang", "ar")
        payload = getattr(request.state, "user", None)

        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=t("errors.unauthorized", lang=lang),
            )

        user_id_str: str = payload.get("sub", "")
        user_role: str = payload.get("role", "")

        try:
            user_id = UUID(user_id_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=t("errors.unauthorized", lang=lang),
            )

        allowed = await check_permission(user_id, user_role, permission_key, redis, db)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=t("errors.permission_denied", lang=lang),
            )

        return payload

    return _check


# ─── Convenience: get current authenticated user payload ──────────────────────

def get_current_user_payload(request: Request) -> dict:
    """Returns the decoded JWT payload. Raises 401 if not authenticated."""
    lang = getattr(request.state, "lang", "ar")
    payload = getattr(request.state, "user", None)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("errors.unauthorized", lang=lang),
        )
    return payload


async def get_current_user_db(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Returns the full User ORM object from the database. Raises 401/403 if invalid."""
    from uuid import UUID as PyUUID
    from app.models.user import User

    payload = get_current_user_payload(request)
    lang = getattr(request.state, "lang", "ar")

    result = await db.execute(
        select(User).where(
            User.id == PyUUID(payload["sub"]),
            User.deleted_at.is_(None),
            User.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("errors.unauthorized", lang=lang),
        )

    return user
