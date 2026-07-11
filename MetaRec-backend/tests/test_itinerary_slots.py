import json

import pytest

from conftest import FakeAsyncClient, make_service, query_intent_json
from llm_service import extract_itinerary_constraints, propose_itinerary_slots

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


def _constraints_json() -> str:
    return json.dumps({
        "location": "Sentosa",
        "date": "2026-08-01",
        "start_time": "09:00",
        "end_time": "18:00",
        "budget_mode": "limited",
        "budget_amount": 150,
        "budget_currency": "SGD",
        "timezone": "Asia/Singapore",
        "pace": "balanced",
    })


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


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_extract_itinerary_constraints_keeps_only_supported_explicit_fields():
    payload = json.dumps({
        "location": "Sentosa",
        "date": "2026-08-01",
        "start_time": "09:00",
        "end_time": "18:00",
        "budget_mode": "limited",
        "budget_amount": 150,
        "budget_currency": "SGD",
        "slots": [{"domain": "attraction"}],
    })
    result = await extract_itinerary_constraints(FakeAsyncClient([payload]), query="plan my day")
    assert result is not None
    assert result["location"] == "Sentosa"
    assert result["budget_amount"] == 150
    assert "slots" not in result


@pytest.mark.asyncio
async def test_service_itinerary_confirmation_persists_constraint_ir():
    service, fake_client = make_service([query_intent_json(), _constraints_json()])

    result = await service.handle_user_request_async(
        "Plan my day out, please",
        user_id="u-slots",
        session_id="c-slots",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    message = result["confirmation_request"].message
    assert "Sentosa" in message and "2026-08-01" in message and "09:00 to 18:00" in message
    planning_request = result["routing"]["metadata"]["planning_request"]
    assert planning_request["days"][0]["start_min"] == 540
    assert planning_request["budget"]["amount"] == 150
    assert result["hitl_state"]["status"] == "awaiting_confirmation"
    assert fake_client.chat.completions.calls == 2


@pytest.mark.asyncio
async def test_service_itinerary_confirmation_requests_missing_constraints():
    service, fake_client = make_service([query_intent_json(), "no usable plan here"])

    result = await service.handle_user_request_async(
        "Plan my day out, please",
        user_id="u-slots-fb",
        session_id="c-slots-fb",
        conversation_history=[],
    )

    form = result["confirmation_request"].preference_form
    assert {"date", "start_time", "end_time", "budget_mode"} <= set(form["missing_required"])
    assert result["hitl_state"]["status"] == "awaiting_clarification"
    assert "planning_request" not in (result["routing"].get("metadata") or {})
    assert fake_client.chat.completions.calls == 2


@pytest.mark.asyncio
async def test_service_explicit_itinerary_mode_does_not_require_keyword_detection():
    service, _ = make_service([query_intent_json(), "no usable plan here"])

    result = await service.handle_user_request_async(
        "Recommend something nice around Chinatown",
        user_id="u-explicit-itinerary",
        session_id="c-explicit-itinerary",
        conversation_history=[],
        itinerary_mode=True,
    )

    assert result["routing"]["mode"] == "itinerary"
    assert result["routing"]["reason"] == "itinerary mode enabled by user"
