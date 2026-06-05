from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from business_models import (
    AuthSessionPayload,
    UserRecord,
    UserRole,
    UserSessionRecord,
    derive_result_id,
    utc_now,
)

REGISTERED_TOKEN = "registered-token"
GUEST_TOKEN = "guest-token"


def _auth_payload(*, token: str, kind: str = "registered") -> AuthSessionPayload:
    uid = str(uuid.uuid4())
    user = UserRecord(
        id=uid,
        kind=kind,
        role=UserRole.USER,
        email="user@example.com" if kind == "registered" else None,
        display_name="Registered" if kind == "registered" else "Guest",
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
    def __init__(self, *payloads: AuthSessionPayload):
        self._by_token = {p.token: p for p in payloads}

    async def session_from_token(self, token: str | None):
        return self._by_token.get(token)


class FakeFeedbackRepository:
    """Mirrors the real ``submit`` contract: resolves a stable result_id, maps
    sentiment -> rating/label, and keys rows on (user_id, result_id) so a re-vote
    updates the same row."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    async def submit(
        self,
        *,
        user_id,
        sentiment,
        reason=None,
        result_id=None,
        task_id=None,
        branch_id=None,
        conversation_id=None,
        ui_message_id=None,
    ):
        resolved = (result_id or "").strip() or None
        if resolved is None and task_id:
            resolved = derive_result_id(task_id, branch_id)
        if not resolved:
            raise ValueError("result_id or task_id is required to attach feedback")

        if sentiment == "up":
            rating, label = 5, None
        elif sentiment == "down":
            rating, label = 1, reason or "others"
        else:
            raise ValueError("sentiment must be 'up' or 'down'")

        key = (user_id, resolved)
        existing = self.rows.get(key)
        feedback_id = existing["feedback_id"] if existing else str(uuid.uuid4())
        row = {
            "feedback_id": feedback_id,
            "result_id": resolved,
            "sentiment": sentiment,
            "rating": rating,
            "reason": label,
        }
        self.rows[key] = row
        return row


@pytest.fixture
def feedback_setup(monkeypatch):
    import main
    import internal.feedback.router as feedback_router_mod

    registered = _auth_payload(token=REGISTERED_TOKEN, kind="registered")
    guest = _auth_payload(token=GUEST_TOKEN, kind="guest")
    fake_auth = FakeAuthRepository(registered, guest)
    fake_feedback = FakeFeedbackRepository()

    monkeypatch.setattr(main, "auth_repository", fake_auth)
    monkeypatch.setattr(feedback_router_mod, "feedback_repository", fake_feedback)
    return main, fake_feedback, registered, guest


def _client_as(main, token):
    client = TestClient(main.app)
    if token:
        client.cookies.set(main.AUTH_COOKIE_NAME, token)
    return client


@pytest.mark.backend_unit
def test_feedback_requires_authentication(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with TestClient(main.app) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up", "result_id": str(uuid.uuid4())})
    assert resp.status_code == 401


@pytest.mark.backend_unit
def test_guest_feedback_blocked(feedback_setup):
    main, repo, _reg, _guest = feedback_setup
    with _client_as(main, GUEST_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up", "result_id": str(uuid.uuid4())})
    assert resp.status_code == 403
    assert repo.rows == {}  # never reached the repository


@pytest.mark.backend_unit
def test_thumb_up_persists_positive_rating(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up", "result_id": str(uuid.uuid4())})
    assert resp.status_code == 200
    feedback = resp.json()["feedback"]
    assert feedback["rating"] == 5
    assert feedback["reason"] is None


@pytest.mark.backend_unit
def test_thumb_down_with_reason(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post(
            "/api/feedback",
            json={"sentiment": "down", "reason": "too_far", "result_id": str(uuid.uuid4())},
        )
    assert resp.status_code == 200
    feedback = resp.json()["feedback"]
    assert feedback["rating"] == 1
    assert feedback["reason"] == "too_far"


@pytest.mark.backend_unit
def test_invalid_reason_rejected(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post(
            "/api/feedback",
            json={"sentiment": "down", "reason": "made_up", "result_id": str(uuid.uuid4())},
        )
    assert resp.status_code == 422


@pytest.mark.backend_unit
def test_thumb_down_without_reason_defaults_to_others(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "down", "result_id": str(uuid.uuid4())})
    assert resp.status_code == 200
    assert resp.json()["feedback"]["reason"] == "others"


@pytest.mark.backend_unit
def test_missing_result_reference_returns_400(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.post("/api/feedback", json={"sentiment": "up"})
    assert resp.status_code == 400


@pytest.mark.backend_unit
def test_revote_updates_same_row(feedback_setup):
    main, repo, _reg, _guest = feedback_setup
    result_id = str(uuid.uuid4())
    with _client_as(main, REGISTERED_TOKEN) as client:
        up = client.post("/api/feedback", json={"sentiment": "up", "result_id": result_id})
        down = client.post(
            "/api/feedback",
            json={"sentiment": "down", "reason": "not_related", "result_id": result_id},
        )
    assert up.status_code == 200 and down.status_code == 200
    # One row per (user, result); the second vote overwrote the first.
    assert len(repo.rows) == 1
    assert up.json()["feedback"]["feedback_id"] == down.json()["feedback"]["feedback_id"]
    assert down.json()["feedback"]["rating"] == 1


@pytest.mark.backend_unit
def test_options_endpoint_shape(feedback_setup):
    main, _repo, _reg, _guest = feedback_setup
    with _client_as(main, REGISTERED_TOKEN) as client:
        resp = client.get("/api/feedback/options")
    assert resp.status_code == 200
    reasons = resp.json()["reasons"]
    codes = {r["code"] for r in reasons}
    assert {"too_far", "not_related", "others"}.issubset(codes)
    assert all(r["label"] for r in reasons)
