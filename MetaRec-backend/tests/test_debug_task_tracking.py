"""Debug arena task tracking resolves a task from the id the chat surfaces.

The chat's "Task ID" copy button (Chat.tsx ProcessingView) yields a bare task id
and nothing else. The tracker used to feed that id into the fully-scoped lookup,
which returns None before touching storage whenever user/conversation are absent
-- so every paste 404'd, valid or not. These tests pin the id-alone path open and
keep the optional filters honest.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from business_models import AuthSessionPayload, UserRecord, UserRole, UserSessionRecord, utc_now

TASK_ID = "11111111-1111-4111-8111-111111111111"
OWNER_ID = "22222222-2222-4222-8222-222222222222"
CONVERSATION_ID = "33333333-3333-4333-8333-333333333333"
TRACK_URL = "/internal/debug/behavior-tests/track"


def _admin_payload() -> AuthSessionPayload:
    uid = str(uuid.uuid4())
    user = UserRecord(
        id=uid,
        kind="registered",
        role=UserRole.ADMIN,
        email="admin@example.com",
        display_name="Acting Admin",
        status="active",
    )
    session = UserSessionRecord(
        id=str(uuid.uuid4()),
        user_id=uid,
        status="active",
        expires_at=utc_now() + timedelta(days=30),
        user=user,
    )
    return AuthSessionPayload(token="admin-token", session=session, user=user)


class FakeService:
    """Mirrors MetaRecService.find_task_status_async: the id resolves, scope narrows."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Optional[str], Optional[str]]] = []
        self.task: Dict[str, Any] = {
            "task_id": TASK_ID,
            "user_id": OWNER_ID,
            "conversation_id": CONVERSATION_ID,
            "status": "completed",
            "progress": 100,
            "message": "done",
            "result": None,
            "error": None,
            "metadata": {},
        }

    async def find_task_status_async(
        self,
        task_id: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self.calls.append((task_id, user_id, session_id))
        if task_id != self.task["task_id"]:
            return None
        if user_id is not None and user_id != self.task["user_id"]:
            return None
        if session_id is not None and session_id != self.task["conversation_id"]:
            return None
        return dict(self.task)


@pytest.fixture
def track_client(monkeypatch):
    monkeypatch.setenv("DEBUG_UI_ENABLED", "1")
    import internal.debug.router as router_mod

    # Not pytest's tmp_path: pytest.ini pins --basetemp inside a gitignored dir
    # that is never created, so that fixture errors out repo-wide.
    with tempfile.TemporaryDirectory() as tmp_root:

        class TmpTraceStorage(router_mod.DebugTraceStorage):
            """Same storage, rooted in a temp dir so runs don't accumulate in the repo."""

            def __init__(self, storage_dir: str = "debug_traces") -> None:
                self.base_dir = Path(tmp_root) / storage_dir
                self.base_dir.mkdir(parents=True, exist_ok=True)
                self._lock = Lock()

        monkeypatch.setattr(router_mod, "DebugTraceStorage", TmpTraceStorage)

        service = FakeService()

        async def require_admin(_request: Request) -> AuthSessionPayload:
            return _admin_payload()

        app = FastAPI()
        app.include_router(router_mod.create_debug_router(lambda: service, require_admin))
        with TestClient(app) as client:
            yield client, service


@pytest.mark.backend_unit
def test_track_resolves_a_task_from_the_pasted_id_alone(track_client):
    client, service = track_client

    resp = client.post(TRACK_URL, json={"task_id": TASK_ID, "poll_interval_ms": 100})

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    # The preflight ran with no scope at all. This is the exact call that used to
    # short-circuit to None before reaching storage, 404-ing every valid id.
    assert service.calls[0] == (TASK_ID, None, None)


@pytest.mark.backend_unit
def test_track_still_narrows_when_scope_is_supplied(track_client):
    client, _service = track_client

    matching = client.post(
        TRACK_URL,
        json={"task_id": TASK_ID, "user_id": OWNER_ID, "conversation_id": CONVERSATION_ID},
    )
    assert matching.status_code == 200, matching.text

    # Optional does not mean ignored: a supplied filter that disagrees still misses.
    wrong_user = client.post(TRACK_URL, json={"task_id": TASK_ID, "user_id": str(uuid.uuid4())})
    assert wrong_user.status_code == 404

    wrong_conversation = client.post(
        TRACK_URL, json={"task_id": TASK_ID, "conversation_id": str(uuid.uuid4())}
    )
    assert wrong_conversation.status_code == 404


@pytest.mark.backend_unit
def test_track_rejects_an_unknown_task_id(track_client):
    client, _service = track_client

    resp = client.post(TRACK_URL, json={"task_id": str(uuid.uuid4())})

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.backend_unit
def test_track_records_the_scope_the_id_resolved_to(track_client):
    client, _service = track_client

    run_id = client.post(TRACK_URL, json={"task_id": TASK_ID}).json()["run_id"]
    config = client.get(f"/internal/debug/behavior-tests/{run_id}").json()["config"]

    # Operator pasted an id only; the trace still shows whose task it is.
    assert config["user_id"] is None
    assert config["resolved_user_id"] == OWNER_ID
    assert config["resolved_conversation_id"] == CONVERSATION_ID


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_find_task_status_async_narrows_only_on_supplied_scope():
    from conftest import make_service

    service, _ = make_service([])
    other_user_task = {"task_id": "task-other", "status": "completed"}
    owned_task = {"task_id": "task-owned", "status": "completed"}
    service._get_session_context(OWNER_ID, CONVERSATION_ID)["tasks"]["task-owned"] = owned_task
    service._get_session_context("someone-else", "other-conversation")["tasks"]["task-other"] = other_user_task

    # Id alone finds either task, regardless of which session context holds it.
    assert await service.find_task_status_async("task-owned") == owned_task
    assert await service.find_task_status_async("task-other") == other_user_task

    # Supplied scope narrows, and full scope behaves like the scoped lookup.
    assert await service.find_task_status_async("task-owned", OWNER_ID) == owned_task
    assert await service.find_task_status_async("task-owned", "someone-else") is None
    assert await service.find_task_status_async("task-owned", OWNER_ID, CONVERSATION_ID) == owned_task
    assert await service.find_task_status_async("task-owned", OWNER_ID, "other-conversation") is None
    assert await service.find_task_status_async("missing") is None
