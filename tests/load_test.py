"""
Locust Load Test — Mobily Support System
=========================================
Run:  locust -f tests/load_test.py --host http://localhost:8000

Tests 100 concurrent users across portal, dashboard, and ticket endpoints.
Green target: p99 < 500ms, error rate < 1% at 100 VUs.
"""
from __future__ import annotations

import json
import random
import string
import time
from typing import Optional

from locust import HttpUser, between, events, task


def _random_phone() -> str:
    return "05" + "".join(random.choices(string.digits, k=8))


def _random_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


# ── Public portal user (unauthenticated) ─────────────────────────────────────

class PublicUser(HttpUser):
    weight       = 60  # 60% of VUs are public portal users
    wait_time    = between(1, 3)
    host         = "http://localhost:8000"

    def on_start(self):
        self.lang = random.choice(["ar", "en"])
        self.client.cookies.set("lang", self.lang)

    @task(10)
    def view_portal(self):
        self.client.get("/portal", name="/portal")

    @task(5)
    def submit_ticket(self):
        self.client.post(
            "/api/tickets/submit",
            data={
                "submitter_name": _random_str(),
                "submitter_phone": _random_phone(),
                "submitter_email": f"{_random_str()}@test.com",
                "subject": "Load test ticket",
                "description": "This is a load test ticket submission.",
                "channel": "portal",
                "priority": random.choice(["low", "medium", "high"]),
            },
            name="/api/tickets/submit",
        )

    @task(3)
    def track_ticket(self):
        # Use a fake ticket number — will return 404 but tests the path
        self.client.get(
            "/api/portal/track?ticket_number=TKT-20260101-0001",
            name="/api/portal/track",
        )

    @task(2)
    def view_status_page(self):
        self.client.get("/status", name="/status")

    @task(1)
    def toggle_language(self):
        self.client.post(
            "/api/language/toggle",
            data={"current_path": "/portal"},
            allow_redirects=False,
            name="/api/language/toggle",
        )


# ── Authenticated agent user ─────────────────────────────────────────────────

class AgentUser(HttpUser):
    weight    = 30  # 30% of VUs are agents
    wait_time = between(2, 5)
    host      = "http://localhost:8000"

    token: Optional[str] = None

    def on_start(self):
        """Login and store token."""
        resp = self.client.post(
            "/api/auth/login",
            json={"username": "agent01", "password": "Password@123"},
            name="/api/auth/login [setup]",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")
        else:
            self.token = None

    def _auth_headers(self) -> dict:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    @task(10)
    def view_dashboard(self):
        self.client.get("/dashboard", headers=self._auth_headers(), name="/dashboard")

    @task(8)
    def poll_queue(self):
        self.client.get(
            "/api/dashboard/queue",
            headers=self._auth_headers(),
            name="/api/dashboard/queue",
        )

    @task(5)
    def kb_search(self):
        self.client.get(
            "/api/kb/search?q=printer",
            headers=self._auth_headers(),
            name="/api/kb/search",
        )

    @task(3)
    def view_ticket_list(self):
        self.client.get("/tickets", headers=self._auth_headers(), name="/tickets")

    @task(1)
    def log_call(self):
        self.client.post(
            "/api/call-log",
            data={"reason": "Test call", "outcome": "resolved", "caller_phone": _random_phone()},
            headers=self._auth_headers(),
            name="/api/call-log",
        )


# ── Supervisor user ──────────────────────────────────────────────────────────

class SupervisorUser(HttpUser):
    weight    = 10  # 10% of VUs are supervisors
    wait_time = between(5, 15)
    host      = "http://localhost:8000"

    token: Optional[str] = None

    def on_start(self):
        resp = self.client.post(
            "/api/auth/login",
            json={"username": "supervisor01", "password": "Password@123"},
            name="/api/auth/login [supervisor]",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(5)
    def view_supervisor_dashboard(self):
        self.client.get("/supervisor", headers=self._h(), name="/supervisor")

    @task(3)
    def poll_workload(self):
        self.client.get("/api/supervisor/workload", headers=self._h(), name="/api/supervisor/workload")

    @task(1)
    def view_team(self):
        self.client.get("/supervisor/team", headers=self._h(), name="/supervisor/team")


# ── Event hooks ───────────────────────────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("\n🚀 Mobily Support load test starting...")
    print(f"   Target: 100 concurrent users, p99 < 500ms, error < 1%")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats.total
    p99   = stats.get_response_time_percentile(0.99)
    err   = stats.fail_ratio * 100
    print(f"\n📊 Load test complete:")
    print(f"   Requests: {stats.num_requests}")
    print(f"   Failures: {stats.num_failures} ({err:.1f}%)")
    print(f"   p99 response: {p99}ms")
    if p99 and p99 < 500 and err < 1:
        print("   ✅ PASSED all targets")
    else:
        print("   ❌ Some targets missed")
