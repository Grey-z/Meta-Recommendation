"""/api/tasks/{task_id}/result must never ship server-only data to the client.

Regression for a leak where the endpoint sanitized only ``metadata`` and served
``items[].raw`` (the unbounded upstream provider payloads) verbatim — the exact
field ``_client_safe_item`` exists to strip on the task-status endpoints.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from business_models import AuthSessionPayload, UserRecord, UserRole, UserSessionRecord, utc_now

USER_TOKEN = "task-result-user-token"


def _auth_payload(user_id: str) -> AuthSessionPayload:
    user = UserRecord(
        id=user_id,
        kind="registered",
        role=UserRole.USER,
        email="user@example.com",
        display_name="Plain User",
        status="active",
    )
    session = UserSessionRecord(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="active",
        expires_at=utc_now() + timedelta(days=30),
        user=user,
    )
    return AuthSessionPayload(token=USER_TOKEN, session=session, user=user)


class FakeAuthRepository:
    cookie_name = "metarec_session"

    def __init__(self, payload: AuthSessionPayload):
        self._payload = payload

    async def session_from_token(self, token: str | None):
        return self._payload if token == self._payload.token else None


class FakeResultRepository:
    def __init__(self, payload):
        self._payload = payload

    async def load_by_task(self, user_id, conversation_id, task_id):
        return self._payload


def _stored_payload() -> dict:
    item = {
        "id": "music_1",
        "domain": "music",
        "title": "Some Song",
        "source": "Last.fm",
        "raw": {"upstream": "unsanitized provider blob"},
    }
    metadata = {
        "domain": "music",
        "items_count": 1,
        "executions": [{"tool": "lastfm.track.discover", "output": ["big"]}],
        "progress_events": [{"stage": "candidate_gather"}],
    }
    return {
        "result_id": str(uuid.uuid4()),
        "task_id": "task-1",
        "branch_id": "branch-main",
        "domain": "music",
        "restaurants": [],
        "items": [dict(item)],
        "thinking_steps": [],
        "metadata": dict(metadata),
        # Legacy rows nested a full duplicate of the result; it must be cleaned too.
        "result": {"items": [dict(item)], "metadata": dict(metadata)},
    }


@pytest.fixture
def client(monkeypatch):
    import main

    user_id = str(uuid.uuid4())
    monkeypatch.setattr(main, "auth_repository", FakeAuthRepository(_auth_payload(user_id)))
    monkeypatch.setattr(main.metarec_service, "result_repository", FakeResultRepository(_stored_payload()))
    client = TestClient(main.app)
    client.cookies.set(main.AUTH_COOKIE_NAME, USER_TOKEN)
    return client, user_id


@pytest.mark.backend_unit
def test_task_result_strips_raw_and_internal_metadata(client):
    http, user_id = client
    body = http.get(f"/api/tasks/task-1/result?user_id={user_id}&conversation_id=c-1").json()

    assert body["items"][0]["title"] == "Some Song"
    assert "raw" not in body["items"][0]
    assert "executions" not in body["metadata"]
    assert "progress_events" not in body["metadata"]
    assert body["metadata"]["items_count"] == 1
    # Legacy nested duplicate is sanitized by the same rules.
    assert "raw" not in body["result"]["items"][0]
    assert "executions" not in body["result"]["metadata"]


@pytest.mark.backend_unit
def test_task_result_requires_auth_and_matching_user(client, monkeypatch):
    import main

    http, user_id = client

    with TestClient(main.app) as anonymous:
        assert anonymous.get(f"/api/tasks/task-1/result?user_id={user_id}&conversation_id=c-1").status_code == 401

    other_user = str(uuid.uuid4())
    assert http.get(f"/api/tasks/task-1/result?user_id={other_user}&conversation_id=c-1").status_code == 403


@pytest.mark.backend_unit
def test_task_result_404_when_nothing_stored(client, monkeypatch):
    import main

    http, user_id = client

    class EmptyRepo:
        async def load_by_task(self, user_id, conversation_id, task_id):
            return None

    monkeypatch.setattr(main.metarec_service, "result_repository", EmptyRepo())
    assert http.get(f"/api/tasks/task-1/result?user_id={user_id}&conversation_id=c-1").status_code == 404
