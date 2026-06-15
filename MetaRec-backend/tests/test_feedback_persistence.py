from __future__ import annotations

import uuid

import pytest

import business_repositories as repo_mod
from business_models import derive_result_id, ensure_uuid


class FakeFeedbackLookup:
    """Stands in for the DB-backed feedback repo: returns recorded votes keyed by
    canonical result_id, and remembers which ids it was asked about."""

    def __init__(self, votes: dict[str, dict]):
        self._votes = votes
        self.asked_with: list[str] | None = None

    async def get_for_results(self, user_id, result_ids):
        self.asked_with = list(result_ids)
        return {rid: self._votes[rid] for rid in result_ids if rid in self._votes}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_annotate_marks_voted_recommendations(monkeypatch):
    user_id = str(uuid.uuid4())
    explicit_result_id = str(uuid.uuid4())
    task_id = "task-abc"
    branch_id = "branch-main"
    derived_result_id = ensure_uuid(derive_result_id(task_id, branch_id))

    conversation = {
        "messages": [
            # rated via an explicit result_id on metadata
            {"branch_id": branch_id, "metadata": {"type": "recommendation", "result_id": explicit_result_id}},
            # rated via id derived from (task_id, branch_id) — the background path
            {"branch_id": branch_id, "metadata": {"type": "recommendation", "task_id": task_id}},
            # a recommendation the user has NOT rated
            {"branch_id": branch_id, "metadata": {"type": "recommendation", "task_id": "task-unrated"}},
            # a non-recommendation message is never touched
            {"branch_id": branch_id, "metadata": {"type": "text"}},
        ]
    }

    fake = FakeFeedbackLookup(
        {
            ensure_uuid(explicit_result_id): {"sentiment": "up", "reason": None},
            derived_result_id: {"sentiment": "down", "reason": "too_far"},
        }
    )
    monkeypatch.setattr(repo_mod, "feedback_repository", fake)

    await repo_mod.conversation_repository._annotate_feedback_state(user_id, conversation)

    msgs = conversation["messages"]
    assert msgs[0]["metadata"]["feedback"] == {"sentiment": "up", "reason": None}
    assert msgs[1]["metadata"]["feedback"] == {"sentiment": "down", "reason": "too_far"}
    assert "feedback" not in msgs[2]["metadata"]
    assert "feedback" not in msgs[3]["metadata"]
    # The lookup is asked exactly for the three resolvable recommendation ids.
    assert set(fake.asked_with or []) == {
        ensure_uuid(explicit_result_id),
        derived_result_id,
        ensure_uuid(derive_result_id("task-unrated", branch_id)),
    }


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_annotate_skips_lookup_when_no_recommendations(monkeypatch):
    calls = {"n": 0}

    class _Spy:
        async def get_for_results(self, user_id, result_ids):
            calls["n"] += 1
            return {}

    monkeypatch.setattr(repo_mod, "feedback_repository", _Spy())
    conversation = {"messages": [{"metadata": {"type": "text"}}, {"metadata": {}}]}
    await repo_mod.conversation_repository._annotate_feedback_state("u", conversation)
    assert calls["n"] == 0


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_annotate_ignores_recommendation_without_result_reference(monkeypatch):
    # A recommendation with neither result_id nor task_id is unresolvable and
    # must be left as-is (e.g. legacy foreground saves).
    fake = FakeFeedbackLookup({})
    monkeypatch.setattr(repo_mod, "feedback_repository", fake)
    conversation = {"messages": [{"metadata": {"type": "recommendation"}}]}
    await repo_mod.conversation_repository._annotate_feedback_state("u", conversation)
    assert "feedback" not in conversation["messages"][0]["metadata"]
    assert fake.asked_with is None  # never queried


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_persist_recommendation_result_accepts_result_model():
    """Regression: the task graph hands ``_persist_recommendation_result`` a
    RecommendationResult *object* (not a dict). It must serialize it and persist a
    row — a swallowed AttributeError here previously meant no result was ever stored,
    so every feedback submission 400'd ("feedback target not found")."""
    from conftest import make_service
    from service import RecommendationResult, Restaurant

    service, _ = make_service([])

    saved: dict = {}

    class FakeResultRepo:
        async def save(self, user_id, conversation_id, branch_id, result_id, payload):
            saved["result_id"] = result_id
            saved["payload"] = payload
            return True

    service.result_repository = FakeResultRepo()

    status = {
        "status": "completed",
        "metadata": {},
        "result": RecommendationResult(
            restaurants=[Restaurant(id="r1", name="Sichuan House")],
            metadata={"domain": "restaurant"},
        ),
    }
    result_id = await service._persist_recommendation_result("u-1", "c-1", "task-1", "branch-main", status)

    assert result_id == derive_result_id("task-1", "branch-main")
    assert saved["payload"]["restaurants"][0]["name"] == "Sichuan House"
    assert saved["payload"]["domain"] == "restaurant"
