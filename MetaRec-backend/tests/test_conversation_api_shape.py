from __future__ import annotations

import pytest


@pytest.mark.backend_unit
def test_conversation_data_accepts_metadata_but_excludes_it_from_response():
    """Regression: _load_conversation surfaces conversation `metadata` (rolling
    context summary) so it round-trips; the ConversationData response model must
    accept that key (extra='forbid' otherwise 500s) but keep it out of the wire."""
    import main

    payload = {
        "id": "c1",
        "user_id": "u1",
        "title": "Chat",
        "model": "Auto",
        "last_message": "",
        "timestamp": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "messages": [],
        "preferences": {},
        "metadata": {"context_summary": {"summary": "x", "summarized_through_message_id": "m1"}},
    }

    # Previously raised ResponseValidationError(extra_forbidden) on `metadata`.
    model = main.ConversationData(**payload)
    dumped = model.model_dump()

    assert "metadata" not in dumped  # internal state stays server-side
    assert dumped["id"] == "c1"
    assert dumped["preferences"] == {}


@pytest.mark.backend_unit
def test_get_conversation_endpoint_serializes_with_metadata(monkeypatch):
    """End-to-end through FastAPI's response validation: GET a conversation whose
    loaded dict carries `metadata` must return 200, not 500, with metadata omitted."""
    import main
    from fastapi.testclient import TestClient

    async def _noop_require_path_user(request, user_id):
        return user_id

    monkeypatch.setattr(main, "require_path_user", _noop_require_path_user)

    class _FakeRepo:
        async def get_full_conversation(self, user_id, conversation_id):
            return {
                "id": conversation_id,
                "user_id": user_id,
                "title": "Chat",
                "model": "Auto",
                "last_message": "",
                "timestamp": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "active_branch_id": "branch-main",
                "branch_selection_state": {},
                "branches": {},
                "messages": [],
                "preferences": {},
                "metadata": {"context_summary": {"summary": "x", "summarized_through_message_id": "m1"}},
            }

    monkeypatch.setattr(main, "conversation_repository", _FakeRepo())

    with TestClient(main.app) as client:
        resp = client.get("/api/conversations/u1/c1")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "c1"
    assert "metadata" not in body
