from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import pyotp
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.core.templates import templates
from app.i18n import t
from app.models.user import User
from app.models.user_session import UserSession
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserMeResponse

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

_ACCESS_TTL = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
_REFRESH_TTL = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400


def _jti_redis_key(jti: str) -> str:
    return f"jti:{jti}"


def _set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.ENVIRONMENT != "development",
        samesite="lax",
        max_age=_ACCESS_TTL,
        path="/",
    )


def _clear_access_cookie(response: Response) -> None:
    response.delete_cookie(key="access_token", path="/")


def _set_csrf_cookie(response: Response, token: str) -> None:
    """Set CSRF token cookie (readable by JS for X-CSRF-Token header)."""
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=False,
        secure=settings.ENVIRONMENT != "development",
        samesite="strict",
        max_age=86400 * 30,  # 30 days
        path="/",
    )


def _clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(key="csrf_token", path="/")


async def _get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(
        select(User)
        .where(User.username == username, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def _get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    from uuid import UUID
    result = await db.execute(
        select(User).where(User.id == UUID(user_id), User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ─── POST /api/auth/login ─────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> TokenResponse:
    lang = getattr(request.state, "lang", "ar")

    user = await _get_user_by_username(db, body.username)

    # Constant-time failure to prevent username enumeration
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("auth.invalid_credentials", lang=lang),
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=t("auth.account_disabled", lang=lang),
        )

    # TOTP validation (required if enabled)
    if user.totp_enabled:
        if not body.totp_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=t("auth.totp_code", lang=lang),
                headers={"X-Requires-TOTP": "true"},
            )
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(body.totp_code, valid_window=1):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=t("auth.invalid_credentials", lang=lang),
            )

    lang_to_use = user.preferred_language

    # Create tokens
    access_token = create_access_token(
        subject=str(user.id),
        role=user.role,
        lang=lang_to_use,
    )
    refresh_token = create_refresh_token(subject=str(user.id))

    access_payload = decode_token(access_token)
    refresh_payload = decode_token(refresh_token)

    # Store JTIs in Redis for revocation
    await redis.setex(_jti_redis_key(access_payload["jti"]), _ACCESS_TTL, "1")
    await redis.setex(_jti_redis_key(refresh_payload["jti"]), _REFRESH_TTL, "1")

    # Persist session record
    session = UserSession(
        user_id=user.id,
        token_hash=_hash_token(access_token),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    db.add(session)

    # Update online status
    user.is_online = True
    user.last_seen_at = datetime.now(timezone.utc)
    await db.commit()

    # Set HttpOnly cookie
    _set_access_cookie(response, access_token)
    # CSRF token for state-changing requests
    _set_csrf_cookie(response, secrets.token_urlsafe(32))

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=_ACCESS_TTL,
        user_id=str(user.id),
        role=user.role,
        lang=lang_to_use,
    )


# ─── POST /api/auth/logout ────────────────────────────────────────────────────

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> Response:
    user_payload = getattr(request.state, "user", None)
    if user_payload:
        # Revoke access token JTI
        jti = user_payload.get("jti")
        if jti:
            await redis.delete(_jti_redis_key(jti))

        # Mark session invalid in DB
        user_id = user_payload.get("sub")
        if user_id:
            result = await db.execute(
                select(UserSession).where(
                    UserSession.user_id == user_id,  # type: ignore[arg-type]
                    UserSession.is_valid.is_(True),
                )
            )
            for sess in result.scalars().all():
                sess.is_valid = False

            # Update online status
            result2 = await db.execute(
                select(User).where(User.id == user_id)  # type: ignore[arg-type]
            )
            user = result2.scalar_one_or_none()
            if user:
                user.is_online = False
            await db.commit()

    _clear_access_cookie(response)
    _clear_csrf_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── POST /api/auth/refresh ───────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> TokenResponse:
    lang = getattr(request.state, "lang", "ar")

    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("errors.unauthorized", lang=lang),
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("errors.unauthorized", lang=lang),
        )

    # Verify refresh JTI is still valid in Redis
    jti = payload.get("jti")
    if not jti or not await redis.exists(_jti_redis_key(jti)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("errors.unauthorized", lang=lang),
        )

    user = await _get_user_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("errors.unauthorized", lang=lang),
        )

    # Revoke old refresh JTI
    await redis.delete(_jti_redis_key(jti))

    # Issue new tokens
    new_access = create_access_token(
        subject=str(user.id), role=user.role, lang=user.preferred_language
    )
    new_refresh = create_refresh_token(subject=str(user.id))

    new_access_payload = decode_token(new_access)
    new_refresh_payload = decode_token(new_refresh)

    await redis.setex(_jti_redis_key(new_access_payload["jti"]), _ACCESS_TTL, "1")
    await redis.setex(_jti_redis_key(new_refresh_payload["jti"]), _REFRESH_TTL, "1")

    _set_access_cookie(response, new_access)
    _set_csrf_cookie(response, secrets.token_urlsafe(32))

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=_ACCESS_TTL,
        user_id=str(user.id),
        role=user.role,
        lang=user.preferred_language,
    )


# ─── GET /api/auth/me ─────────────────────────────────────────────────────────

@router.get("/me", response_model=UserMeResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> UserMeResponse:
    lang = getattr(request.state, "lang", "ar")
    user_payload = getattr(request.state, "user", None)

    if not user_payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("errors.unauthorized", lang=lang),
        )

    user = await _get_user_by_id(db, user_payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("errors.unauthorized", lang=lang),
        )

    return UserMeResponse.model_validate(user)
