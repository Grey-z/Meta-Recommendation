import json

import pytest

from conftest import FakeAsyncClient, make_service, query_intent_json
from llm_service import extract_itinerary_constraints

pytestmark = pytest.mark.backend_unit


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
        "interest_terms": ["university campus", "academic architecture"],
        "slots": [{"domain": "attraction"}],
    })
    result = await extract_itinerary_constraints(FakeAsyncClient([payload]), query="plan my day")
    assert result is not None
    assert result["location"] == "Sentosa"
    assert result["budget_amount"] == 150
    assert result["interest_terms"] == ["university campus", "academic architecture"]
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
    # Date and the daily window now default (tomorrow, 09:00-22:00) rather than
    # blocking the confirmation; budget stays required.
    assert "budget_mode" in set(form["missing_required"])
    assert {"date", "daily_start_time", "daily_end_time"}.isdisjoint(form["missing_required"])
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
