"""
Shared pytest fixtures for Mobily Support test suite.

Database: uses a real PostgreSQL test database (TEST_DATABASE_URL env var).
Falls back to SQLite+aiosqlite for CI environments without Postgres.

Pattern:
  - session-scoped engine + table creation
  - function-scoped session with ROLLBACK isolation (no test pollution)
  - HTTPX AsyncClient with DB override
  - Pre-built user fixtures for each role
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

UTC = timezone.utc

# ── Database URL ────────────────────────────────────────────────────────────────
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///./test.db",
)

# Use PostgreSQL-compatible flag for feature detection
IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")


# ── Engine + tables ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def engine():
    from app.core.database import Base

    eng = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
        **({"connect_args": {"check_same_thread": False}} if not IS_POSTGRES else {}),
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session. Each test rolls back at the end."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ── HTTP Client ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db) -> AsyncGenerator[AsyncClient, None]:
    from app.main import app
    from app.core.database import get_db

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Mock Redis ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_redis():
    """In-memory Redis-like dict for testing."""
    from unittest.mock import AsyncMock, MagicMock

    store: dict = {}
    ttls: dict  = {}

    redis = MagicMock()
    redis.get   = AsyncMock(side_effect=lambda k: store.get(k))
    redis.set   = AsyncMock(side_effect=lambda k, v, *a, **kw: store.__setitem__(k, v))
    redis.setex = AsyncMock(side_effect=lambda k, t, v: store.__setitem__(k, v))
    redis.incr  = AsyncMock(side_effect=lambda k: store.__setitem__(k, store.get(k, 0) + 1) or store[k])
    redis.expire= AsyncMock(return_value=True)
    redis.exists= AsyncMock(side_effect=lambda k: int(k in store))
    redis.delete= AsyncMock(side_effect=lambda k: store.pop(k, None))
    redis.lpush = AsyncMock(return_value=1)
    redis.sadd  = AsyncMock(return_value=1)
    redis.srem  = AsyncMock(return_value=1)
    redis.smembers = AsyncMock(return_value=set())
    redis.ping  = AsyncMock(return_value=True)
    return redis


# ── User fixtures ───────────────────────────────────────────────────────────────

def _make_user(role: str, **kwargs) -> dict:
    uid = str(uuid.uuid4())
    return {
        "sub":          uid,
        "role":         role,
        "username":     kwargs.get("username", f"test_{role}"),
        "full_name_ar": kwargs.get("full_name_ar", f"مستخدم {role}"),
        "full_name_en": kwargs.get("full_name_en", f"Test {role.title()}"),
        "email":        kwargs.get("email", f"{role}@test.com"),
        "exp":          9999999999,
        "iat":          1000000000,
    }


@pytest.fixture
def employee_user():
    return _make_user("employee")


@pytest.fixture
def supervisor_user():
    return _make_user("supervisor")


@pytest.fixture
def manager_user():
    return _make_user("manager")


@pytest.fixture
def admin_user():
    return _make_user("admin")


@pytest.fixture
def auth_headers(employee_user):
    """JWT-signed headers for the employee user."""
    return _jwt_headers(employee_user)


@pytest.fixture
def supervisor_headers(supervisor_user):
    return _jwt_headers(supervisor_user)


@pytest.fixture
def manager_headers(manager_user):
    return _jwt_headers(manager_user)


@pytest.fixture
def admin_headers(admin_user):
    return _jwt_headers(admin_user)


def _jwt_headers(user_payload: dict) -> dict:
    """Generate a real JWT token for the test user."""
    import jwt as _jwt
    from app.core.config import settings

    token = _jwt.encode(user_payload, settings.JWT_PRIVATE_KEY or settings.SECRET_KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


# ── Sample data factories ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def sample_ticket(db):
    """Create a minimal ticket in the DB for tests that need one."""
    from app.models.ticket import Ticket

    ticket = Ticket(
        id=uuid.uuid4(),
        ticket_number="TKT-20260101-0001",
        subject="Test ticket",
        description="Test description",
        status="open",
        priority="medium",
        channel="portal",
        submitter_name="Test User",
        submitter_phone="0501234567",
        version=1,
        reopen_count=0,
        sla_breached=False,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    db.add(ticket)
    await db.flush()
    return ticket


@pytest_asyncio.fixture
async def sample_category(db):
    from app.models.category import Category

    cat = Category(
        id=uuid.uuid4(),
        name_ar="تقنية المعلومات",
        name_en="IT",
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    db.add(cat)
    await db.flush()
    return cat


@pytest_asyncio.fixture
async def sample_sla_policy(db):
    from app.models.sla import SLAPolicy

    policy = SLAPolicy(
        id=uuid.uuid4(),
        name_ar="سياسة اختبار",
        name_en="Test Policy",
        priority="medium",
        response_minutes=60,
        resolution_minutes=480,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    db.add(policy)
    await db.flush()
    return policy
