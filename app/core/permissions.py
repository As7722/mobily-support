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

# ─── Default role permissions (same as manager UI; DB overrides these) ─────────
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "dashboard.view":       ["employee", "supervisor", "manager", "admin"],
    "tickets.view":         ["employee", "supervisor", "manager", "admin"],
    "tickets.create":       ["employee", "supervisor", "manager", "admin"],
    "tickets.edit":         ["employee", "supervisor", "manager", "admin"],
    "tickets.delete":       ["manager", "admin"],
    "supervisor.view":      ["supervisor", "manager", "admin"],
    "supervisor.team":      ["supervisor", "manager", "admin"],
    "manager.view":         ["manager", "admin"],
    "manager.settings":     ["manager", "admin"],
    "admin.view":           ["admin"],
    "kb.view":              ["employee", "supervisor", "manager", "admin"],
    "kb.edit":              ["supervisor", "manager", "admin"],
    "reports.view":         ["supervisor", "manager", "admin"],
}

ALL_ROLES = ["employee", "supervisor", "manager", "admin"]

_PERM_CACHE_TTL = 900  # 15 minutes


def get_default_permissions_for_role(role: str) -> set[str]:
    """صلاحيات افتراضية للدور بدون DB (لاحتياطي الـ middleware عند الفشل)."""
    role = (role or "").strip().lower()
    if not role:
        return set()
    if role == "admin":
        return set(DEFAULT_ROLE_PERMISSIONS.keys())
    return {k for k, roles in DEFAULT_ROLE_PERMISSIONS.items() if role in roles}


def _perm_cache_key(role: str) -> str:
    return f"perms:{(role or '').strip().lower()}"


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
      4. DB lookup + merge with DEFAULT_ROLE_PERMISSIONS → cache effective set
    """
    user_role = (user_role or "").strip().lower()

    # 1. Hardcoded absolute denial
    if permission_key in HARDCODED_DENIED:
        return False

    # 2. Admin bypass
    if user_role == "admin":
        return True

    # 2b. Manager always has manager.view and manager.settings (so users page works without DB seed)
    if user_role == "manager" and permission_key in ("manager.view", "manager.settings"):
        return True

    # 3. Redis cache (optional — skip so manager toggle always reflects; set _USE_PERM_CACHE = True to enable)
    _USE_PERM_CACHE = False
    if _USE_PERM_CACHE:
        cache_key = _perm_cache_key(user_role)
        cached: set[str] = await redis.smembers(cache_key)
        if cached:
            return permission_key in cached

    # 4. DB lookup: load ALL rows for this role (both granted and denied), then merge with defaults
    from app.models.permission import RolePermission

    result = await db.execute(
        select(RolePermission.permission_key, RolePermission.is_granted).where(
            RolePermission.role == user_role,
        )
    )
    db_overrides: dict[str, bool] = {row[0]: row[1] for row in result.fetchall()}

    # Effective granted = default for perm, overridden by DB if row exists
    granted: set[str] = set()
    for perm_key, default_roles in DEFAULT_ROLE_PERMISSIONS.items():
        if perm_key in db_overrides:
            if db_overrides[perm_key]:
                granted.add(perm_key)
        else:
            if user_role in default_roles:
                granted.add(perm_key)

    if _USE_PERM_CACHE and granted:
        await redis.sadd(_perm_cache_key(user_role), *granted)
        await redis.expire(_perm_cache_key(user_role), _PERM_CACHE_TTL)

    return permission_key in granted


async def get_effective_permissions_for_role(role: str, db: AsyncSession) -> set[str]:
    """
    Returns the set of permission keys granted for this role (defaults + DB overrides).
    Used by middleware to set request.state.effective_permissions for UI (show/hide buttons).
    """
    role = (role or "").strip().lower()
    if not role:
        return set()

    # Admin has all defined permissions (for sidebar and any permission-gated UI)
    if role == "admin":
        return set(DEFAULT_ROLE_PERMISSIONS.keys())

    from app.models.permission import RolePermission

    result = await db.execute(
        select(RolePermission.permission_key, RolePermission.is_granted).where(
            RolePermission.role == role,
        )
    )
    db_overrides: dict[str, bool] = {row[0]: row[1] for row in result.fetchall()}

    granted: set[str] = set()
    for perm_key, default_roles in DEFAULT_ROLE_PERMISSIONS.items():
        if perm_key in db_overrides:
            if db_overrides[perm_key]:
                granted.add(perm_key)
        else:
            if role in default_roles:
                granted.add(perm_key)
    return granted


async def invalidate_permission_cache(role: str, redis: aioredis.Redis) -> None:
    """Call after any role_permissions update to flush the cache for that role."""
    key = _perm_cache_key(role)
    await redis.delete(key)


async def invalidate_all_permission_caches(redis: aioredis.Redis) -> None:
    """Call after any role_permissions change so all roles see fresh permissions."""
    for role in ALL_ROLES:
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


# ─── Require manager or admin (for /manager/users so it always works) ─────────

def require_manager_or_admin():
    """Dependency: allow only manager or admin. Use for /manager/users so it works without DB permissions."""

    async def _check(
        request: Request,
    ):
        lang = getattr(request.state, "lang", "ar")
        payload = getattr(request.state, "user", None)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=t("errors.unauthorized", lang=lang),
            )
        role = (payload.get("role") or "").strip().lower()
        if role not in ("manager", "admin"):
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
