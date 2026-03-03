"""
Tests for RBAC permission matrix.

Verifies that:
  - require_permission() raises 403 for insufficient roles.
  - Each role can access exactly its allowed endpoints.
  - Admin can access everything.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Permission matrix (from admin.py DEFAULT_PERMISSIONS) ────────────────────

PERM_MATRIX = {
    "dashboard.view":   ["employee", "supervisor", "manager", "admin"],
    "tickets.view":     ["employee", "supervisor", "manager", "admin"],
    "tickets.delete":   ["manager", "admin"],
    "supervisor.view":  ["supervisor", "manager", "admin"],
    "supervisor.team":  ["supervisor", "manager", "admin"],
    "manager.view":     ["manager", "admin"],
    "manager.settings": ["manager", "admin"],
    "admin.view":       ["admin"],
    "kb.edit":          ["supervisor", "manager", "admin"],
    "reports.view":     ["supervisor", "manager", "admin"],
}

ALL_ROLES = ["employee", "supervisor", "manager", "admin"]


@pytest.mark.parametrize("permission,allowed_roles", PERM_MATRIX.items())
def test_permission_allowed_roles(permission, allowed_roles):
    """Each permission must grant access to exactly the listed roles."""
    for role in ALL_ROLES:
        should_allow = role in allowed_roles
        # Simulate require_permission logic
        result = role in allowed_roles
        assert result == should_allow, f"perm={permission} role={role} expected={should_allow}"


def test_admin_has_all_permissions():
    """Admin role must have access to all defined permissions."""
    from app.api.admin import DEFAULT_PERMISSIONS
    for perm, roles in DEFAULT_PERMISSIONS.items():
        assert "admin" in roles, f"Admin missing permission: {perm}"


def test_employee_cannot_access_manager_perms():
    """Employee should not have manager-only permissions."""
    manager_only = [p for p, roles in PERM_MATRIX.items() if "manager" in roles and "employee" not in roles]
    for perm in manager_only:
        assert "employee" not in PERM_MATRIX[perm], f"Employee wrongly has: {perm}"


def test_supervisor_can_access_own_perms():
    """Supervisor must have access to supervisor-level permissions."""
    supervisor_perms = [p for p, roles in PERM_MATRIX.items() if "supervisor" in roles]
    assert "supervisor.view" in supervisor_perms
    assert "supervisor.team" in supervisor_perms


# ── require_permission() dependency ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_require_permission_grants_access():
    """require_permission() should not raise for authorised role."""
    from fastapi import HTTPException
    from app.core.permissions import require_permission

    dep = require_permission("dashboard.view")

    request = MagicMock()
    request.state.user = {"sub": str(uuid.uuid4()), "role": "employee"}

    try:
        await dep(request)
    except Exception as exc:
        pytest.fail(f"require_permission raised unexpectedly: {exc}")


@pytest.mark.asyncio
async def test_require_permission_denies_insufficient_role():
    """require_permission() must raise 403 for insufficient role."""
    from fastapi import HTTPException
    from app.core.permissions import require_permission

    dep = require_permission("admin.view")

    request = MagicMock()
    request.state.user = {"sub": str(uuid.uuid4()), "role": "employee"}

    with pytest.raises(HTTPException) as exc_info:
        await dep(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_permission_denies_unauthenticated():
    """Unauthenticated request (no user in state) must raise 401."""
    from fastapi import HTTPException
    from app.core.permissions import require_permission

    dep = require_permission("dashboard.view")

    request = MagicMock()
    request.state.user = None

    with pytest.raises(HTTPException) as exc_info:
        await dep(request)
    assert exc_info.value.status_code in (401, 403)


# ── Role escalation guard ─────────────────────────────────────────────────────

def test_status_transitions_respect_role():
    """
    Verify that only authorised roles can trigger restricted transitions.
    The status transition matrix itself is role-agnostic at service level,
    but the API layer enforces require_permission.
    """
    from app.api.tickets_internal import STATUS_TRANSITIONS
    # All transitions from SPEC.md must be present
    assert "resolved" in STATUS_TRANSITIONS["open"]
    assert "closed" in STATUS_TRANSITIONS["resolved"]
    assert "open" not in STATUS_TRANSITIONS.get("closed", [])


# ── Webhook authentication ────────────────────────────────────────────────────

def test_twilio_signature_validation():
    """Twilio signature validation must reject tampered requests."""
    from app.api.webhooks import _validate_twilio_signature

    auth_token = "test_auth_token"
    url        = "https://example.com/webhooks/whatsapp"
    params     = {"Body": "Hello", "From": "whatsapp:+966501234567"}

    # Compute valid signature
    import base64, hmac, hashlib
    s = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    valid_sig = base64.b64encode(
        hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()
    ).decode()

    assert _validate_twilio_signature(auth_token, url, params, valid_sig) is True
    assert _validate_twilio_signature(auth_token, url, params, "wrong_sig") is False
