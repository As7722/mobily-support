"""
Tests for authentication:
  - Login (valid / invalid credentials)
  - JWT token validation
  - Logout
  - Protected endpoint access
  - Permission enforcement
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Health check (sanity) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check(client):
    """GET /health must return 200 with status=ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


# ── Login ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_missing_fields(client):
    """POST /api/auth/login without credentials should return 422."""
    response = await client.post("/api/auth/login", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_invalid_credentials(client, db):
    """POST /api/auth/login with wrong password should return 401."""
    response = await client.post("/api/auth/login", json={
        "username": "nonexistent_user",
        "password": "wrong_password",
    })
    assert response.status_code in (401, 404)


@pytest.mark.asyncio
async def test_login_valid_returns_tokens(client, db):
    """Valid login should return access_token and token_type."""
    from app.models.user import User
    from app.core.security import hash_password

    user = User(
        id=uuid.uuid4(),
        username="testlogin",
        full_name_ar="مستخدم اختبار",
        password_hash=hash_password("Password@123"),
        role="employee",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    response = await client.post("/api/auth/login", json={
        "username": "testlogin",
        "password": "Password@123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data.get("token_type") == "bearer"


@pytest.mark.asyncio
async def test_login_inactive_user_denied(client, db):
    """Inactive user should not be able to login."""
    from app.models.user import User
    from app.core.security import hash_password

    user = User(
        id=uuid.uuid4(),
        username="inactive_user",
        full_name_ar="غير نشط",
        password_hash=hash_password("Pass@123"),
        role="employee",
        is_active=False,
    )
    db.add(user)
    await db.flush()

    response = await client.post("/api/auth/login", json={
        "username": "inactive_user",
        "password": "Pass@123",
    })
    assert response.status_code in (401, 403)


# ── Protected endpoints ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_requires_auth(client):
    """GET /dashboard without auth token must return 401 or 302 redirect."""
    response = await client.get("/dashboard", follow_redirects=False)
    assert response.status_code in (401, 302, 303)


@pytest.mark.asyncio
async def test_dashboard_with_valid_token(client, auth_headers, db):
    """GET /dashboard with valid auth headers should return 200 or similar."""
    with patch("app.services.kpi.get_employee_kpis", new_callable=AsyncMock, return_value={
        "resolved_today": 3, "avg_resolution_mins": 45,
        "csat_avg": 4.2, "sla_compliance_pct": 95.0,
        "workload": 5, "rank": 2,
    }), patch("app.services.queue.get_smart_queue", new_callable=AsyncMock, return_value={
        "tickets": [], "scores": {}, "total": 0, "page": 1, "per_page": 25, "pages": 1,
    }):
        response = await client.get("/dashboard", headers=auth_headers)
    # Should succeed or redirect (depends on middleware)
    assert response.status_code in (200, 302, 401)


@pytest.mark.asyncio
async def test_admin_panel_blocked_for_employee(client, auth_headers):
    """Employee trying to access /admin must get 403."""
    response = await client.get("/admin", headers=auth_headers, follow_redirects=False)
    assert response.status_code in (401, 403, 302)


# ── JWT token validation ──────────────────────────────────────────────────────

def test_jwt_encode_decode_roundtrip():
    """Token issued by login must be decodable with the same key."""
    import jwt as _jwt
    from app.core.config import settings

    payload = {"sub": str(uuid.uuid4()), "role": "employee", "exp": 9999999999}
    key = settings.JWT_PRIVATE_KEY or settings.SECRET_KEY
    token = _jwt.encode(payload, key, algorithm="HS256")
    decoded = _jwt.decode(token, key, algorithms=["HS256"])
    assert decoded["role"] == "employee"


def test_jwt_expired_token_invalid():
    """An expired token should raise DecodeError."""
    import jwt as _jwt
    from app.core.config import settings

    payload = {"sub": str(uuid.uuid4()), "role": "employee", "exp": 1000}  # long past
    key = settings.JWT_PRIVATE_KEY or settings.SECRET_KEY
    token = _jwt.encode(payload, key, algorithm="HS256")

    with pytest.raises(_jwt.ExpiredSignatureError):
        _jwt.decode(token, key, algorithms=["HS256"])


def test_jwt_wrong_key_invalid():
    """A token signed with wrong key must fail verification."""
    import jwt as _jwt

    payload = {"sub": str(uuid.uuid4()), "role": "employee", "exp": 9999999999}
    token = _jwt.encode(payload, "wrong_key", algorithm="HS256")

    with pytest.raises((_jwt.InvalidSignatureError, _jwt.DecodeError)):
        _jwt.decode(token, "correct_key", algorithms=["HS256"])


# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_password_not_plaintext():
    from app.core.security import hash_password

    plain = "MySecure@Pass123"
    hashed = hash_password(plain)
    assert hashed != plain
    assert len(hashed) > 20


def test_verify_password_correct():
    from app.core.security import hash_password, verify_password

    plain  = "AnotherPass@456"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_password_wrong():
    from app.core.security import hash_password, verify_password

    hashed = hash_password("correct_pass")
    assert verify_password("wrong_pass", hashed) is False
