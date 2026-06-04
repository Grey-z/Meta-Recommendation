from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from business_models import AuthSessionPayload, UserRecord, UserRole, UserSessionRecord, utc_now
from business_repositories import (
    ConcurrencyConflictError,
    UserNotFoundError,
)

ADMIN_TOKEN = "admin-token"
USER_TOKEN = "user-token"


def _auth_payload(*, user_id: str | None = None, token: str, role: UserRole) -> AuthSessionPayload:
    uid = user_id or str(uuid.uuid4())
    user = UserRecord(
        id=uid,
        kind="registered",
        role=role,
        email="admin@example.com" if role is UserRole.ADMIN else "user@example.com",
        display_name="Acting Admin" if role is UserRole.ADMIN else "Plain User",
        status="active",
    )
    session = UserSessionRecord(
        id=str(uuid.uuid4()),
        user_id=uid,
        status="active",
        expires_at=utc_now() + timedelta(days=30),
        user=user,
    )
    return AuthSessionPayload(token=token, session=session, user=user)


class FakeAuthRepository:
    """Resolves the session cookie to a pre-baked payload (admin or user)."""

    cookie_name = "metarec_session"

    def __init__(self, *payloads: AuthSessionPayload):
        self._by_token = {p.token: p for p in payloads}

    async def session_from_token(self, token: str | None):
        return self._by_token.get(token)


def _user_dict(*, user_id=None, role="user", status="active", email=None, updated_at="2026-01-01T00:00:00+00:00"):
    uid = user_id or str(uuid.uuid4())
    return {
        "id": uid,
        "kind": "registered",
        "role": role,
        "email": email or f"{uid[:8]}@example.com",
        "display_name": None,
        "status": status,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": updated_at,
        "last_seen_at": None,
    }


class FakeAdminRepository:
    ALLOWED_STATUSES = {"active", "suspended", "deleted"}

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.created: list[dict] = []
        self.deleted_ids: list[str] = []

    def seed(self, record: dict) -> dict:
        self.users[record["id"]] = record
        return record

    async def get_stats(self):
        return {
            "tasks": {"total": 3, "completed": 2, "errored": 1, "success_rate": 0.6667},
            "tokens": {
                "total_tokens": 1000,
                "prompt_tokens": 600,
                "completion_tokens": 400,
                "cost_usd": 0.12,
                "last_7d_total_tokens": 200,
            },
            "users": {"total": 5, "registered": 3, "guests": 2, "new_registered_last_7d": 1},
            "conversations": {"total_created": 4, "active_sessions": 2},
            "feedback": {"total": 0, "satisfied": 0, "unsatisfied": 0, "satisfaction_ratio": None, "reasons": []},
            "generated_at": "2026-06-04T00:00:00+00:00",
        }

    async def list_users(self, *, limit=20, offset=0, search=None, role=None, status=None, kind=None):
        items = list(self.users.values())
        if role:
            items = [u for u in items if u["role"] == role]
        if status:
            items = [u for u in items if u["status"] == status]
        if kind:
            items = [u for u in items if u["kind"] == kind]
        if search:
            needle = search.lower()
            items = [
                u
                for u in items
                if needle in (u.get("email") or "").lower()
                or needle in (u.get("display_name") or "").lower()
            ]
        total = len(items)
        return items[offset : offset + limit], total

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def count_active_admins(self, *, exclude_user_id=None):
        return sum(
            1
            for u in self.users.values()
            if u["role"] == "admin" and u["status"] == "active" and u["id"] != exclude_user_id
        )

    async def create_user(self, *, email, password, display_name=None, role="user", status="active"):
        if "@" not in email:
            raise ValueError("a valid email is required")
        if not password or len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        rec = _user_dict(role=role, status=status, email=email.strip().lower())
        rec["display_name"] = display_name
        self.users[rec["id"]] = rec
        self.created.append(rec)
        return rec

    async def update_user(
        self,
        *,
        user_id,
        expected_updated_at=None,
        role=None,
        status=None,
        display_name=None,
        display_name_provided=False,
    ):
        row = self.users.get(user_id)
        if row is None:
            raise UserNotFoundError("user not found")
        if expected_updated_at is not None and expected_updated_at != row["updated_at"]:
            raise ConcurrencyConflictError("stale")
        if role is not None:
            row["role"] = role
        if status is not None:
            row["status"] = status
        if display_name_provided:
            row["display_name"] = display_name
        row["updated_at"] = "2026-02-02T00:00:00+00:00"
        return row

    async def soft_delete_user(self, *, user_id):
        row = self.users.get(user_id)
        if row is None:
            raise UserNotFoundError("user not found")
        row["status"] = "deleted"
        self.deleted_ids.append(user_id)
        return row


@pytest.fixture
def admin_setup(monkeypatch):
    """Wire a fake auth repo (admin + plain user) and a fake admin repo."""
    import main
    import internal.admin.router as admin_router_mod

    admin_payload = _auth_payload(token=ADMIN_TOKEN, role=UserRole.ADMIN)
    user_payload = _auth_payload(token=USER_TOKEN, role=UserRole.USER)
    fake_auth = FakeAuthRepository(admin_payload, user_payload)
    fake_admin = FakeAdminRepository()

    monkeypatch.setattr(main, "auth_repository", fake_auth)
    monkeypatch.setattr(admin_router_mod, "admin_repository", fake_admin)
    return main, fake_admin, admin_payload, user_payload


def _client_as(main, token):
    client = TestClient(main.app)
    if token:
        client.cookies.set(main.AUTH_COOKIE_NAME, token)
    return client


@pytest.mark.backend_unit
def test_admin_endpoints_require_admin_role(admin_setup):
    main, _fake_admin, _admin, _user = admin_setup

    # Anonymous → 401
    with TestClient(main.app) as client:
        assert client.get("/api/admin/stats").status_code == 401

    # Authenticated non-admin → 403
    with _client_as(main, USER_TOKEN) as client:
        assert client.get("/api/admin/stats").status_code == 403

    # Admin → 200
    with _client_as(main, ADMIN_TOKEN) as client:
        assert client.get("/api/admin/stats").status_code == 200


@pytest.mark.backend_unit
def test_stats_endpoint_returns_aggregate_shape(admin_setup):
    main, _fake_admin, _admin, _user = admin_setup
    with _client_as(main, ADMIN_TOKEN) as client:
        body = client.get("/api/admin/stats").json()
    for key in ("tasks", "tokens", "users", "conversations", "feedback", "generated_at"):
        assert key in body
    assert body["tasks"]["success_rate"] == 0.6667
    assert body["users"]["new_registered_last_7d"] == 1


@pytest.mark.backend_unit
def test_list_users_is_paginated(admin_setup):
    main, fake_admin, _admin, _user = admin_setup
    for i in range(5):
        fake_admin.seed(_user_dict(email=f"u{i}@example.com"))

    with _client_as(main, ADMIN_TOKEN) as client:
        page1 = client.get("/api/admin/users", params={"limit": 2, "offset": 0}).json()
        page2 = client.get("/api/admin/users", params={"limit": 2, "offset": 2}).json()

    assert page1["total"] == 5
    assert page1["limit"] == 2 and page1["offset"] == 0
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert {u["id"] for u in page1["items"]}.isdisjoint({u["id"] for u in page2["items"]})


@pytest.mark.backend_unit
def test_create_user(admin_setup):
    main, fake_admin, _admin, _user = admin_setup
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.post(
            "/api/admin/users",
            json={
                "email": "New@Example.com",
                "password": "supersecret",
                "display_name": "Newbie",
                "role": "admin",
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "admin"
    assert len(fake_admin.created) == 1


@pytest.mark.backend_unit
def test_create_user_rejects_short_password(admin_setup):
    main, _fake_admin, _admin, _user = admin_setup
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.post(
            "/api/admin/users",
            json={"email": "x@example.com", "password": "short"},
        )
    assert resp.status_code == 400


@pytest.mark.backend_unit
def test_self_role_downgrade_blocked(admin_setup):
    main, fake_admin, admin_payload, _user = admin_setup
    # Acting admin exists in the table as an active admin and edits itself.
    fake_admin.seed(_user_dict(user_id=admin_payload.user.id, role="admin"))
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.patch(f"/api/admin/users/{admin_payload.user.id}", json={"role": "user"})
    assert resp.status_code == 400
    assert "own admin role" in resp.json()["detail"]


@pytest.mark.backend_unit
def test_self_deactivate_blocked(admin_setup):
    main, fake_admin, admin_payload, _user = admin_setup
    fake_admin.seed(_user_dict(user_id=admin_payload.user.id, role="admin"))
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.patch(f"/api/admin/users/{admin_payload.user.id}", json={"status": "suspended"})
    assert resp.status_code == 400


@pytest.mark.backend_unit
def test_last_admin_downgrade_blocked(admin_setup):
    main, fake_admin, _admin, _user = admin_setup
    # The only active admin in the table is a *different* user than the actor.
    target = fake_admin.seed(_user_dict(role="admin"))
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.patch(f"/api/admin/users/{target['id']}", json={"role": "user"})
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"]


@pytest.mark.backend_unit
def test_stale_update_returns_409(admin_setup):
    main, fake_admin, _admin, _user = admin_setup
    target = fake_admin.seed(_user_dict(role="user", updated_at="2026-01-01T00:00:00+00:00"))
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.patch(
            f"/api/admin/users/{target['id']}",
            json={"display_name": "Renamed", "expected_updated_at": "1999-01-01T00:00:00+00:00"},
        )
    assert resp.status_code == 409


@pytest.mark.backend_unit
def test_update_with_matching_token_succeeds(admin_setup):
    main, fake_admin, _admin, _user = admin_setup
    target = fake_admin.seed(_user_dict(role="user", updated_at="2026-01-01T00:00:00+00:00"))
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.patch(
            f"/api/admin/users/{target['id']}",
            json={"status": "suspended", "expected_updated_at": "2026-01-01T00:00:00+00:00"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


@pytest.mark.backend_unit
def test_self_delete_blocked(admin_setup):
    main, fake_admin, admin_payload, _user = admin_setup
    fake_admin.seed(_user_dict(user_id=admin_payload.user.id, role="admin"))
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.delete(f"/api/admin/users/{admin_payload.user.id}")
    assert resp.status_code == 400
    assert "own account" in resp.json()["detail"]


@pytest.mark.backend_unit
def test_soft_delete_marks_status_and_retains_row(admin_setup):
    main, fake_admin, _admin, _user = admin_setup
    target = fake_admin.seed(_user_dict(role="user"))
    with _client_as(main, ADMIN_TOKEN) as client:
        resp = client.delete(f"/api/admin/users/{target['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    # Row is retained (soft delete), not removed from the table.
    assert target["id"] in fake_admin.users
    assert fake_admin.users[target["id"]]["status"] == "deleted"
