from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from business_models import AuthSessionPayload, UserRecord, UserRole, UserSessionRecord, utc_now

pytestmark = pytest.mark.backend_unit


def _auth_payload(
    *, user_id: str | None = None, token: str = "test-token", role: UserRole = UserRole.USER
) -> AuthSessionPayload:
    uid = user_id or str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    user = UserRecord(
        id=uid,
        kind="guest",
        role=role,
        status="active",
    )
    session = UserSessionRecord(
        id=session_id,
        user_id=uid,
        anonymous_device_id=str(uuid.uuid4()),
        status="active",
        expires_at=utc_now() + timedelta(days=30),
        user=user,
    )
    return AuthSessionPayload(token=token, session=session, user=user)


class FakeAuthRepository:
    cookie_name = "metarec_session"

    def __init__(self, payload: AuthSessionPayload | None = None):
        self.payload = payload or _auth_payload()
        self.revoked: list[str | None] = []

    async def get_or_create_guest(self, *, device_id: str, user_agent: str | None = None, ttl_days: int = 30):
        return self.payload

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
        existing_guest_user_id: str | None = None,
        ttl_days: int = 30,
    ):
        self.existing_guest_user_id = existing_guest_user_id
        return self.payload

    async def login(self, *, email: str, password: str, ttl_days: int = 30):
        return self.payload

    async def session_from_token(self, token: str | None):
        return self.payload if token == self.payload.token else None

    async def revoke_token(self, token: str | None):
        self.revoked.append(token)


def test_guest_login_sets_cookie_and_session_endpoint_uses_it(monkeypatch):
    import main

    payload = _auth_payload(token="guest-token")
    fake_auth = FakeAuthRepository(payload)
    monkeypatch.setattr(main, "auth_repository", fake_auth)

    with TestClient(main.app) as client:
        login_response = client.post("/api/auth/guest", json={"device_id": "browser-device-id"})
        assert login_response.status_code == 200
        assert client.cookies.get(main.AUTH_COOKIE_NAME) == "guest-token"
        assert login_response.json()["user"]["id"] == payload.user.id

        session_response = client.get("/api/auth/session")
        assert session_response.status_code == 200
        assert session_response.json()["session"]["user_id"] == payload.user.id


def test_process_rejects_user_id_outside_current_session(monkeypatch):
    import main

    payload = _auth_payload(token="session-token")
    fake_auth = FakeAuthRepository(payload)
    monkeypatch.setattr(main, "auth_repository", fake_auth)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("service should not run for a mismatched authenticated user")

    monkeypatch.setattr(main.metarec_service, "handle_user_request_async", fail_if_called)

    with TestClient(main.app) as client:
        client.cookies.set(main.AUTH_COOKIE_NAME, "session-token")
        response = client.post(
            "/api/process",
            json={"query": "find dinner", "user_id": str(uuid.uuid4())},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "user_id does not match authenticated session"


def test_process_uses_session_user_when_request_user_id_is_default(monkeypatch):
    import main

    payload = _auth_payload(token="session-token")
    fake_auth = FakeAuthRepository(payload)
    monkeypatch.setattr(main, "auth_repository", fake_auth)

    captured: dict[str, str] = {}

    async def fake_handle(query, user_id, *args, **kwargs):
        captured["query"] = query
        captured["user_id"] = user_id
        return {
            "type": "llm_reply",
            "llm_reply": "hello",
            "metadata": {"source": "test"},
        }

    monkeypatch.setattr(main.metarec_service, "handle_user_request_async", fake_handle)

    with TestClient(main.app) as client:
        client.cookies.set(main.AUTH_COOKIE_NAME, "session-token")
        response = client.post("/api/process", json={"query": "hello", "user_id": "default"})

    assert response.status_code == 200
    assert response.json()["llm_reply"] == "hello"
    assert captured == {"query": "hello", "user_id": payload.user.id}


def test_register_upgrades_current_guest_session(monkeypatch):
    import main

    payload = _auth_payload(token="registered-token")
    guest_payload = _auth_payload(user_id=payload.user.id, token="guest-token")
    fake_auth = FakeAuthRepository(payload)

    async def fake_session_from_token(token: str | None):
        return guest_payload if token == "guest-token" else None

    fake_auth.session_from_token = fake_session_from_token
    monkeypatch.setattr(main, "auth_repository", fake_auth)

    with TestClient(main.app) as client:
        client.cookies.set(main.AUTH_COOKIE_NAME, "guest-token")
        response = client.post(
            "/api/auth/register",
            json={"email": "user@example.com", "password": "password123"},
        )

    assert response.status_code == 200
    assert fake_auth.existing_guest_user_id == guest_payload.user.id


def test_require_admin_session_enforces_admin_role(monkeypatch):
    import main

    admin_payload = _auth_payload(role=UserRole.ADMIN)
    user_payload = _auth_payload(role=UserRole.USER)

    async def as_admin(_request):
        return admin_payload

    async def as_user(_request):
        return user_payload

    async def as_anonymous(_request):
        return None

    # Admin session is allowed through.
    monkeypatch.setattr(main, "get_optional_auth_session", as_admin)
    assert asyncio.run(main.require_admin_session(object())) is admin_payload

    # Authenticated non-admin is forbidden (403).
    monkeypatch.setattr(main, "get_optional_auth_session", as_user)
    with pytest.raises(HTTPException) as forbidden:
        asyncio.run(main.require_admin_session(object()))
    assert forbidden.value.status_code == 403

    # Unauthenticated is rejected (401).
    monkeypatch.setattr(main, "get_optional_auth_session", as_anonymous)
    with pytest.raises(HTTPException) as unauthorized:
        asyncio.run(main.require_admin_session(object()))
    assert unauthorized.value.status_code == 401


def test_password_hash_accepts_common_registered_password_length():
    from business_repositories import pwd_context

    password = "password"
    hashed = pwd_context.hash(password)

    assert hashed
    assert pwd_context.verify(password, hashed)
