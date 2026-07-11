import json

import pytest

from conftest import FakeAsyncClient, make_service, query_intent_json
from llm_service import propose_itinerary_slots

pytestmark = pytest.mark.backend_unit


def _slots_json() -> str:
    return json.dumps(
        {
            "slots": [
                {"domain": "attraction", "label": "Beach morning", "time": "09:30"},
                {"domain": "restaurant", "label": "Seafood lunch", "time": "12:00"},
                {"domain": "hotel", "label": "Check in and rest", "time": "15:00"},
            ]
        }
    )


@pytest.mark.asyncio
async def test_propose_itinerary_slots_parses_valid_plan():
    client = FakeAsyncClient([_slots_json()])

    slots = await propose_itinerary_slots(client, query="plan my day in Sentosa")

    assert [slot["domain"] for slot in slots] == ["attraction", "restaurant", "hotel"]
    assert slots[0] == {
        "domain": "attraction",
        "source_domain": "attraction",
        "status": "ready",
        "tool_tags": ["#place", "#attraction"],
        "slot_index": 0,
        "slot_label": "Beach morning",
        "slot_time": "09:30",
        "slot_role": "activity",
        "slot_preferences": {},
    }


@pytest.mark.asyncio
async def test_propose_itinerary_slots_rejects_invalid_plans():
    bad_domain = json.dumps(
        {"slots": [{"domain": "spa", "label": "x", "time": "10:00"}, {"domain": "restaurant"}]}
    )
    assert await propose_itinerary_slots(FakeAsyncClient([bad_domain]), query="q") is None

    too_few = json.dumps({"slots": [{"domain": "restaurant"}]})
    assert await propose_itinerary_slots(FakeAsyncClient([too_few]), query="q") is None

    assert await propose_itinerary_slots(FakeAsyncClient(["not json at all"]), query="q") is None

    assert await propose_itinerary_slots(FakeAsyncClient([RuntimeError("boom")]), query="q") is None


@pytest.mark.asyncio
async def test_propose_itinerary_slots_rejects_invalid_time():
    payload = json.dumps(
        {
            "slots": [
                {"domain": "attraction", "label": "", "time": "25:99"},
                {"domain": "restaurant", "label": "Lunch", "time": "12:30"},
            ]
        }
    )

    assert await propose_itinerary_slots(FakeAsyncClient([payload]), query="q") is None


@pytest.mark.asyncio
async def test_propose_itinerary_slots_rejects_non_place_and_non_chronological_plans():
    non_place = json.dumps({"slots": [
        {"domain": "movie", "label": "Film", "time": "10:00"},
        {"domain": "restaurant", "label": "Lunch", "time": "12:30"},
    ]})
    backwards = json.dumps({"slots": [
        {"domain": "attraction", "label": "Late", "time": "15:00"},
        {"domain": "restaurant", "label": "Lunch", "time": "12:30"},
    ]})
    assert await propose_itinerary_slots(FakeAsyncClient([non_place]), query="q") is None
    assert await propose_itinerary_slots(FakeAsyncClient([backwards]), query="q") is None


@pytest.mark.asyncio
async def test_service_itinerary_confirmation_uses_llm_plan():
    # analyze (1) -> slot proposer (2); the confirmation itself stays deterministic.
    service, fake_client = make_service([query_intent_json(), _slots_json()])

    result = await service.handle_user_request_async(
        "Plan my day out, please",
        user_id="u-slots",
        session_id="c-slots",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    message = result["confirmation_request"].message
    assert "Beach morning" in message and "Seafood lunch" in message
    assert result["routing"]["metadata"]["slot_plan_source"] == "llm"
    assert [task["domain"] for task in result["routing"]["domain_tasks"]] == ["attraction", "restaurant", "hotel"]
    # The LLM plan is what the eventual task will execute (persisted in HITL state).
    assert result["hitl_state"]["routing"]["domain_tasks"][0]["slot_label"] == "Beach morning"
    assert fake_client.chat.completions.calls == 2


@pytest.mark.asyncio
async def test_service_itinerary_confirmation_falls_back_to_template():
    service, fake_client = make_service([query_intent_json(), "no usable plan here"])

    result = await service.handle_user_request_async(
        "Plan my day out, please",
        user_id="u-slots-fb",
        session_id="c-slots-fb",
        conversation_history=[],
    )

    message = result["confirmation_request"].message
    assert "Lunch" in message  # deterministic template labels survive
    assert "slot_plan_source" not in (result["routing"].get("metadata") or {})
    assert fake_client.chat.completions.calls == 2
