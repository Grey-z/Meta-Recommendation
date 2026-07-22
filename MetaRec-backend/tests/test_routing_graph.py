import json

import pytest

from conftest import confirm_yes_json, make_service, query_intent_json
from langgraph_metarec.graphs.routing_graph import (
    build_routing_graph,
    run_routing_graph,
    tool_tags_for_domain,
)


@pytest.mark.backend_unit
def test_routing_graph_uses_langgraph_compiled_executor():
    graph = build_routing_graph()

    assert type(graph).__name__ == "CompiledStateGraph"
    assert hasattr(graph, "ainvoke")


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_routes_restaurant_to_place_restaurant_tags():
    route = await run_routing_graph(
        query="Recommend spicy restaurants in Chinatown",
        intent="query",
        preferences={"location": "Chinatown"},
    )

    assert route.domain == "restaurant"
    assert route.execution_domain == "restaurant"
    assert route.status == "ready"
    assert route.mode == "single_domain"
    assert route.tool_tags == ["#place", "#restaurant"]
    assert route.is_restaurant_execution


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_explicit_itinerary_mode_overrides_ambiguous_intent_but_not_domain_lock():
    forced = await run_routing_graph(
        query="Recommend something nice",
        intent="query",
        preferences={"domain": "restaurant"},
        force_itinerary=True,
    )
    assert forced.mode == "itinerary"
    assert forced.reason == "itinerary mode enabled by user"
    assert forced.domain_confidence == 1.0

    locked = await run_routing_graph(
        query="Plan my day",
        intent="query",
        domain_lock="movie",
        force_itinerary=True,
    )
    assert locked.mode == "single_domain"
    assert locked.domain == "movie"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_domain_lock_overrides_query_classification():
    route = await run_routing_graph(
        query="Recommend a restaurant for tonight",
        intent="query",
        domain_lock="movie",
    )

    assert route.domain == "movie"
    assert route.execution_domain == "movie"
    assert route.status == "ready"
    assert route.tool_tags == ["#thing", "#movie"]
    assert route.reason == "domain locked by service type: movie"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_restaurant_domain_lock_sets_restaurant_scope():
    route = await run_routing_graph(
        query="Recommend a film for tonight",
        intent="query",
        domain_lock="restaurant",
    )

    assert route.domain == "restaurant"
    assert route.execution_domain == "restaurant"
    assert route.status == "ready"
    assert route.tool_tags == ["#place", "#restaurant"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_retries_unknown_then_returns_domain_error():
    route = await run_routing_graph(query="Recommend something nice tonight", intent="query")

    assert route.domain == "unknown"
    assert route.execution_domain is None
    assert route.status == "domain_error"
    assert route.mode == "domain_error"
    assert route.tool_tags == []
    assert route.metadata["clarification_required"] is True


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_hotel_routes_ready():
    route = await run_routing_graph(query="Recommend a hotel for tonight", intent="query")

    assert route.domain == "hotel"
    assert route.execution_domain == "hotel"
    assert route.status == "ready"
    assert route.tool_tags == ["#place", "#hotel"]
    assert route.can_execute
    assert not route.is_restaurant_execution


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_attraction_routes_ready():
    route = await run_routing_graph(query="What are the best attractions in Sentosa?", intent="query")

    assert route.domain == "attraction"
    assert route.execution_domain == "attraction"
    assert route.status == "ready"
    assert route.tool_tags == ["#place", "#attraction"]
    assert route.can_execute
    assert not route.is_restaurant_execution


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_attraction_entities_hint_without_colliding_with_product():
    # `attraction_types` alone hints attraction even with no domain keyword...
    route = await run_routing_graph(
        query="anything fun this weekend",
        intent="query",
        preferences={"attraction_types": ["museum"]},
    )
    assert route.domain == "attraction"
    assert route.status == "ready"
    assert "entities matched attraction" in (route.reason or "")

    # ...while product's category keys still hint product alone — the two entity
    # key sets must never overlap (guards the attraction_types naming choice).
    route = await run_routing_graph(
        query="anything nice",
        intent="query",
        preferences={"category": "smartphone"},
    )
    assert route.domain == "product"
    assert "entities matched product" in (route.reason or "")


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_future_single_domain_does_not_execute_restaurant(monkeypatch):
    # Every keyword-mapped domain is connected now, so future-domain coverage
    # drives the graph with a synthetic recognized-but-not-connected domain.
    import langgraph_metarec.graphs.routing_graph as routing_module

    monkeypatch.setattr(
        routing_module, "classify_domain", lambda query: ("travel", 0.8, "matched travel keywords")
    )
    route = await run_routing_graph(query="Plan me a trip", intent="query")

    assert route.domain == "travel"
    assert route.execution_domain is None
    assert route.status == "future_domain"
    assert not route.can_execute


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_unknown_is_not_coerced_to_restaurant_by_preferences():
    # An ambiguous query must NOT be forced into restaurant just because
    # restaurant preferences happen to be present — it stays unknown and falls
    # through to the graceful "what we support" reply.
    route = await run_routing_graph(
        query="Recommend something nice tonight",
        intent="query",
        preferences={"restaurant_types": ["casual"], "location": "Chinatown"},
    )

    assert route.domain == "unknown"
    assert route.execution_domain is None
    assert route.status == "domain_error"
    # The retry ran (enriched with the preference terms) but still did not match
    # any registered domain — no restaurant coercion.
    assert route.metadata.get("retry_count") == 1


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_uses_llm_preference_domain_before_keywords():
    route = await run_routing_graph(
        query="万能青年旅店有什么歌好听呀",
        intent="query",
        preferences={
            "domain": "music",
            "artist": "万能青年旅店",
            "query": "万能青年旅店有什么歌好听呀",
        },
    )

    assert route.domain == "music"
    assert route.execution_domain == "music"
    assert route.status == "ready"
    assert route.tool_tags == ["#thing", "#music"]
    assert "LLM preference domain" in (route.reason or "")


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_uses_domain_specific_entities_when_domain_missing():
    route = await run_routing_graph(
        query="有什么好听呀",
        intent="query",
        preferences={"artist": "万能青年旅店"},
    )

    assert route.domain == "music"
    assert route.execution_domain == "music"
    assert route.status == "ready"
    assert "entities matched music" in (route.reason or "")


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_multi_domain_is_structured_future_route():
    route = await run_routing_graph(query="Recommend a movie and restaurant for tonight", intent="query")

    assert route.domain == "multi_domain"
    assert route.mode == "multi_domain"
    assert route.status == "ready"
    assert route.execution_domain == "multi_domain"
    assert {task["domain"] for task in route.domain_tasks if task["status"] == "ready"} == {"movie", "restaurant"}


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_keeps_explicit_multi_domain_query_when_llm_returns_one_domain():
    route = await run_routing_graph(
        query="Recommend an attraction and a hotel in Sentosa",
        intent="query",
        preferences={
            "domain": "attraction",
            "attraction_types": ["museum"],
            "location": "Sentosa",
        },
    )

    assert route.domain == "multi_domain"
    assert {task["domain"] for task in route.domain_tasks if task["status"] == "ready"} == {
        "attraction",
        "hotel",
    }


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_uses_structured_multi_domain_preferences():
    route = await run_routing_graph(
        query="Plan both for me",
        intent="query",
        preferences={
            "domain": "multi_domain",
            "domains": ["attraction", "hotel"],
            "location": "Sentosa",
        },
    )

    assert route.domain == "multi_domain"
    assert {task["domain"] for task in route.domain_tasks if task["status"] == "ready"} == {
        "attraction",
        "hotel",
    }


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_does_not_turn_location_anchor_into_second_task():
    route = await run_routing_graph(
        query="Find attractions near my hotel in Sentosa",
        intent="query",
        preferences={"domain": "attraction", "location": "Sentosa"},
    )

    assert route.domain == "attraction"
    assert route.mode == "single_domain"


@pytest.mark.backend_unit
def test_tool_tags_for_domain_normalizes_tags():
    assert tool_tags_for_domain("hotel") == ["#place", "#hotel"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_itinerary_routes_ready():
    route = await run_routing_graph(query="Plan my day in Sentosa", intent="query")

    assert route.domain == "itinerary"
    assert route.execution_domain == "itinerary"
    assert route.mode == "itinerary"
    assert route.status == "ready"
    assert route.can_execute
    assert route.domain_tasks == []
    assert route.metadata["planning_phase"] == "constraints_pending"


@pytest.mark.backend_unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Plan a one-day itinerary with museums and dinner in Sentosa",
        "帮我规划一天的行程，想去博物馆和吃晚饭",
    ],
)
async def test_routing_graph_itinerary_beats_multi_domain(query):
    # Mixed attraction+restaurant wording must become ONE itinerary, not a
    # multi-domain fan-out — the itinerary check runs before classification.
    route = await run_routing_graph(query=query, intent="query")

    assert route.mode == "itinerary"
    assert route.domain == "itinerary"


@pytest.mark.backend_unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "帮我plan一下NTU半日游",       # the reported miss: mixed-language, half-day
        "Plan a half-day tour of Sentosa",
        "帮我安排一个新加坡两日游",
    ],
)
async def test_routing_graph_itinerary_matches_partial_day_phrasings(query):
    route = await run_routing_graph(query=query, intent="query")

    assert route.mode == "itinerary"
    assert route.domain == "itinerary"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_honors_llm_itinerary_domain_signal():
    # No trigger keyword in the text — the intent LLM's semantic frame carries
    # the itinerary intent instead (paraphrases like "from morning till night").
    route = await run_routing_graph(
        query="What should I do in Sentosa from morning till night?",
        intent="query",
        preferences={"domain": "itinerary", "location": "Sentosa"},
    )

    assert route.mode == "itinerary"
    assert "LLM preference domain: itinerary" in (route.reason or "")


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_does_not_preallocate_stops_for_lodging_request():
    route = await run_routing_graph(
        query="Plan my day trip in Sentosa and a hotel to stay overnight", intent="query"
    )

    assert route.domain_tasks == []
    assert route.metadata["planning_phase"] == "constraints_pending"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_routing_graph_domain_lock_bypasses_itinerary_detection():
    # A service-type lock is an explicit single-domain intent.
    route = await run_routing_graph(query="Plan my day in Sentosa", intent="query", domain_lock="restaurant")

    assert route.domain == "restaurant"
    assert route.mode == "single_domain"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_itinerary_query_requests_explicit_constraints():
    service, fake_client = make_service([query_intent_json(), "no usable constraints"])

    result = await service.handle_user_request_async(
        "Plan my day out, please",
        user_id="u-itinerary",
        session_id="c-itinerary",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["routing"]["mode"] == "itinerary"
    assert result["routing"]["execution_domain"] == "itinerary"
    message = result["confirmation_request"].message
    assert "around Chinatown" in message
    assert "Budget isn't set yet" in message
    form = result["confirmation_request"].preference_form
    assert form is not None and form["domain"] == "itinerary"
    assert any(field["key"] == "location" and field["required"] for field in form["fields"])
    # Date and the daily window now default (tomorrow, 09:00-22:00) instead of
    # blocking, so budget is the only day-framing constraint still outstanding.
    assert "budget_mode" in set(form["missing_required"])
    assert {"date", "daily_start_time", "daily_end_time"}.isdisjoint(form["missing_required"])
    assert result["hitl_state"]["status"] == "awaiting_clarification"
    assert fake_client.chat.completions.calls == 2


@pytest.mark.backend_unit
def test_itinerary_profile_location_is_a_visible_suggestion():
    from langgraph_metarec.graphs.request_orchestrator import _enrich_itinerary_preferences

    enriched = _enrich_itinerary_preferences(
        {"domain": "itinerary"},
        {"demographics": {"location": "Singapore"}},
    )
    assert enriched["location"] == "Singapore"
    assert enriched["timezone"] == "Asia/Singapore"
    assert enriched["_itinerary_field_sources"]["location"] == "profile"
    assert enriched["_itinerary_field_sources"]["timezone"] == "system"


@pytest.mark.backend_unit
def test_itinerary_confirmation_states_only_provided_constraints():
    from langgraph_metarec.graphs.request_orchestrator import _itinerary_confirmation

    complete = _itinerary_confirmation("plan a day", {"mode": "itinerary"}, {
        "location": "Sentosa",
        "date": "2026-08-01",
        "start_time": "10:00",
        "end_time": "18:00",
        "budget_mode": "limited",
        "budget_amount": 100,
        "budget_currency": "SGD",
        "timezone": "Asia/Singapore",
        "style": "sightseeing",
        "pace": "balanced",
    })
    assert complete["message"] == (
            "I'll dynamically plan a balanced sightseeing itinerary around Sentosa on 2026-08-01, "
            "from 10:00 to 18:00, with a total trip budget of 100 SGD per person, "
            "timezone Asia/Singapore. Review these constraints, then confirm to start planning."
    )

    partial = _itinerary_confirmation("plan a day", {"mode": "itinerary"}, {
        "location": "Sentosa",
        "date": "2026-08-01",
        "start_time": "10:00",
        "end_time": "18:00",
        "timezone": "Asia/Singapore",
        "style": "sightseeing",
        "pace": "balanced",
    })
    assert partial["message"] == (
        "I'll dynamically plan a balanced sightseeing itinerary around Sentosa on 2026-08-01, "
        "from 10:00 to 18:00, timezone Asia/Singapore. "
        "Budget isn't set yet; fill it in below, then confirm to start planning."
    )

    empty = _itinerary_confirmation("plan a day", {"mode": "itinerary"}, {})
    # With nothing supplied, the message surfaces the effective defaults (tomorrow,
    # 09:00-22:00) it will actually plan with, since round 1 shows no form.
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tomorrow = (datetime.now(ZoneInfo("Asia/Singapore")).date() + timedelta(days=1)).isoformat()
    assert empty["message"] == (
        f"I'll dynamically plan an itinerary on {tomorrow} (default date), "
        "from 09:00 to 22:00 (default hours). "
        "Destination / area, budget, timezone, itinerary style, and pace aren't set yet; "
        "fill them in below, then confirm to start planning."
    )


@pytest.mark.backend_unit
def test_itinerary_confirmation_missing_fields_are_the_form_missing_fields():
    from langgraph_metarec.graphs.request_orchestrator import _itinerary_confirmation

    confirmation = _itinerary_confirmation("plan a day", {"mode": "itinerary"}, {
        "location": "Sentosa",
        "date": "2026-08-01",
        "start_time": "10:00",
        "end_time": "18:00",
        "budget_mode": "limited",
        "budget_amount": 100,
        "style": "sightseeing",
        "pace": "balanced",
    })
    form = confirmation["preference_form"]
    assert set(form["missing_required"]) == {"budget_currency", "timezone"}
    assert "currency and timezone aren't set yet" in confirmation["message"].lower()


@pytest.mark.backend_unit
def test_itinerary_ambiguous_location_builds_quick_actions():
    from langgraph_metarec.graphs.request_orchestrator import _itinerary_confirmation

    confirmation = _itinerary_confirmation("plan a day", {"mode": "itinerary"}, {
        "location": "NTU",
        "location_options": [
            {"label": "NTU Singapore", "value": "Nanyang Technological University, Singapore"},
            {"label": "NTU Taiwan", "value": "National Taiwan University, Taipei"},
        ],
    })
    assert confirmation["message"] == "Which destination did you mean?"
    assert [action["label"] for action in confirmation["quick_actions"]] == ["NTU Singapore", "NTU Taiwan"]
    assert confirmation["quick_actions"][0]["preference_patch"]["location_resolution"] == "selected"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_itinerary_confirm_without_required_constraints_does_not_create_task():
    service, _ = make_service([query_intent_json(), "not constraints"])
    first = await service.handle_user_request_async(
        "Plan my day out, please",
        user_id="u-constraint-gate",
        session_id="c-constraint-gate",
        conversation_history=[],
    )
    hitl = dict(first["hitl_state"])
    hitl["action"] = "confirm"
    second = await service.handle_user_request_async(
        "confirm",
        user_id="u-constraint-gate",
        session_id="c-constraint-gate",
        conversation_history=[],
        hitl_state=hitl,
    )
    assert second["type"] == "confirmation"
    assert "task_id" not in second
    assert second["hitl_state"]["status"] == "awaiting_clarification"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_itinerary_confirm_with_invalid_time_window_returns_clarification():
    service, _ = make_service([query_intent_json(), "not constraints"])
    first = await service.handle_user_request_async(
        "Plan a day in Sentosa",
        user_id="u-invalid-itinerary-time",
        session_id="c-invalid-itinerary-time",
        conversation_history=[],
    )
    hitl = {
        **first["hitl_state"],
        "action": "confirm",
        "preferences": {
            **(first["hitl_state"].get("preferences") or {}),
            "location": "Sentosa, Singapore",
            "date": "2026-08-01",
            "horizon_days": 1,
            "daily_start_time": "18:00",
            "daily_end_time": "09:00",
            "budget_mode": "unlimited",
            "timezone": "Asia/Singapore",
            "style": "mixed",
            "pace": "balanced",
        },
    }

    second = await service.handle_user_request_async(
        "confirm",
        user_id="u-invalid-itinerary-time",
        session_id="c-invalid-itinerary-time",
        conversation_history=[],
        hitl_state=hitl,
    )

    assert second["type"] == "confirmation"
    assert "task_id" not in second
    assert second["intent"] == "confirmation_no"
    assert second["hitl_state"]["status"] == "awaiting_clarification"
    assert "end time must be later" in second["confirmation_request"].message.lower()
    assert {"daily_start_time", "daily_end_time"} <= set(
        second["confirmation_request"].preference_form["missing_required"]
    )


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_multi_day_confirm_normalizes_stale_none_lodging_and_creates_task():
    service, _ = make_service([query_intent_json(), "not constraints"])
    first = await service.handle_user_request_async(
        "Plan a two-day trip in Singapore",
        user_id="u-multi-day-lodging-normalization",
        session_id="c-multi-day-lodging-normalization",
        conversation_history=[],
    )
    captured = {}

    async def fake_create_task_async(*args, **kwargs):
        captured["preferences"] = args[1]
        captured["route"] = args[7]
        return "task-multi-day-normalized"

    service.create_task_async = fake_create_task_async
    hitl = {
        **first["hitl_state"],
        "action": "confirm",
        "preferences": {
            **(first["hitl_state"].get("preferences") or {}),
            "location": "Singapore",
            "date": "2026-08-01",
            "horizon_days": 2,
            "daily_start_time": "09:00",
            "daily_end_time": "19:00",
            "budget_mode": "unlimited",
            "timezone": "Asia/Singapore",
            "travelers": 2,
            "rooms": 1,
            "style": "mixed",
            "pace": "balanced",
            "lodging_mode": "none",
        },
    }

    second = await service.handle_user_request_async(
        "confirm",
        user_id="u-multi-day-lodging-normalization",
        session_id="c-multi-day-lodging-normalization",
        conversation_history=[],
        hitl_state=hitl,
    )

    assert second["type"] == "task_created"
    assert second["task_id"] == "task-multi-day-normalized"
    assert captured["preferences"]["lodging_mode"] == "recommend"
    assert captured["route"]["metadata"]["planning_request"]["lodging"]["mode"] == "recommend"
    assert "hotel" in [task["domain"] for task in captured["route"]["domain_tasks"]]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_two_day_itinerary_requests_multi_day_constraints():
    constraints = json.dumps({
        "location": "Singapore", "horizon_days": 2, "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
    })
    service, _ = make_service([query_intent_json(), constraints])
    result = await service.handle_user_request_async(
        "Plan a two-day itinerary in Singapore",
        user_id="u-two-day",
        session_id="c-two-day",
        conversation_history=[],
    )
    assert result["hitl_state"]["status"] == "awaiting_clarification"
    assert "selecting one shared hotel for 1 nights" in result["confirmation_request"].message
    missing = set(result["confirmation_request"].preference_form["missing_required"])
    # Multi-day still requires occupancy; date and the daily window now default.
    assert {"travelers", "rooms"} <= missing
    assert {"date", "daily_start_time", "daily_end_time"}.isdisjoint(missing)


@pytest.mark.backend_unit
def test_three_day_confirmation_summarizes_shared_lodging_and_trip_budget():
    from langgraph_metarec.graphs.request_orchestrator import (
        _itinerary_confirmation,
        _itinerary_form_incomplete,
    )

    preferences = {
        "location": "Singapore",
        "date": "2026-08-01",
        "horizon_days": 3,
        "daily_start_time": "09:00",
        "daily_end_time": "19:00",
        "budget_mode": "limited",
        "budget_amount": 900,
        "budget_currency": "SGD",
        "timezone": "Asia/Singapore",
        "travelers": 2,
        "rooms": 1,
        "style": "mixed",
        "pace": "balanced",
        "lodging_mode": "recommend",
    }
    confirmation = _itinerary_confirmation(
        "Plan three days in Singapore",
        {"mode": "itinerary"},
        preferences,
    )

    assert _itinerary_form_incomplete(confirmation, preferences) is False
    assert "2026-08-01 through 2026-08-03 (3 days)" in confirmation["message"]
    assert "daily from 09:00 to 19:00" in confirmation["message"]
    assert "total trip budget of 900 SGD per person" in confirmation["message"]
    assert "one shared hotel for 2 nights" in confirmation["message"]
    assert "2 travelers in 1 room" in confirmation["message"]


@pytest.mark.backend_unit
def test_four_day_confirmation_requires_shorter_horizon():
    from langgraph_metarec.graphs.request_orchestrator import (
        _itinerary_confirmation,
        _itinerary_form_incomplete,
    )

    preferences = {"location": "Singapore", "horizon_days": 4}
    confirmation = _itinerary_confirmation(
        "Plan four days in Singapore",
        {"mode": "itinerary"},
        preferences,
    )

    assert _itinerary_form_incomplete(confirmation, preferences) is True
    assert "one to three consecutive days" in confirmation["message"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_itinerary_hotel_origin_requires_an_unambiguous_anchor():
    service, _ = make_service([query_intent_json(), "no usable constraints"])
    result = await service.handle_user_request_async(
        "Plan my day from my hotel in Sentosa",
        user_id="u-hotel-anchor",
        session_id="c-hotel-anchor",
        conversation_history=[],
    )

    assert result["routing"]["metadata"]["hotel_anchor_requested"] is True
    assert result["routing"]["domain_tasks"] == []
    form = result["confirmation_request"].preference_form
    hotel_field = next(field for field in form["fields"] if field["key"] == "hotel_anchor")
    assert hotel_field["required"] is True
    assert "hotel_anchor" in form["missing_required"]
    assert "starting hotel" in result["confirmation_request"].message.lower()


@pytest.mark.backend_unit
def test_meaningful_preference_overlay_drops_empty_values():
    from langgraph_metarec.graphs.request_orchestrator import _meaningful_preference_overlay

    assert _meaningful_preference_overlay(
        {"location": "", "budget": "< 50 SGD", "attraction_types": [], "stars": None, "mood": "chill"}
    ) == {"budget": "< 50 SGD", "mood": "chill"}
    assert _meaningful_preference_overlay(None) == {}
    assert _meaningful_preference_overlay({"location": 0}) == {"location": 0}  # falsy-but-real survives


@pytest.mark.backend_unit
def test_itinerary_enrichment_preserves_explicit_university_theme():
    from langgraph_metarec.graphs.request_orchestrator import (
        _enrich_itinerary_preferences,
        _itinerary_confirmation,
    )

    enriched = _enrich_itinerary_preferences({
        "query": "Hey, plan me a University day trip around Singapore",
        "location": "Singapore",
    }, None)

    assert "university-campus" in enriched["attraction_types"]
    assert "university campus" in enriched["interest_terms"]
    assert enriched["_itinerary_field_sources"]["attraction_types"] == "user"
    confirmation = _itinerary_confirmation(
        enriched["query"], {"mode": "itinerary"}, enriched,
    )
    assert "focused on university campus" in confirmation["message"]
    interests_field = next(
        field for field in confirmation["preference_form"]["fields"]
        if field["key"] == "attraction_types"
    )
    assert interests_field["value"] == ["university-campus"]


@pytest.mark.backend_unit
def test_itinerary_anchor_does_not_add_hotel_gather_task():
    from langgraph_metarec.graphs.request_orchestrator import _itinerary_gather_tasks

    tasks = _itinerary_gather_tasks(
        {"mode": "itinerary", "metadata": {"hotel_anchor_requested": True}},
        {
            "anchors": {"start": {"query": "Beach Hotel"}, "end": {"query": "Beach Hotel"}},
            "hard_constraints": {"meal_obligations": ["lunch"]},
        },
    )
    assert [task["domain"] for task in tasks] == ["attraction", "restaurant"]


@pytest.mark.backend_unit
def test_recommended_multi_day_lodging_adds_one_hotel_gather_task():
    from langgraph_metarec.graphs.request_orchestrator import _itinerary_gather_tasks

    tasks = _itinerary_gather_tasks(
        {"mode": "itinerary"},
        {
            "lodging": {"mode": "recommend", "nights": 2},
            "hard_constraints": {"meal_obligations": [{"day_index": 0, "meal": "lunch"}]},
        },
    )
    assert [task["domain"] for task in tasks] == ["attraction", "restaurant", "hotel"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_resolved_anchor_completes_form_without_reopening_refinement():
    from langgraph_metarec.graphs.request_orchestrator import (
        RequestOrchestratorAdapters,
        _itinerary_confirmation,
        _itinerary_form_incomplete,
        _resolve_itinerary_anchor_preferences,
    )

    async def unused_async(*args, **kwargs):
        return {}

    async def resolve_anchor(query, destination, provider_id=None):
        return [{
            "id": "hotel-1",
            "domain": "hotel",
            "title": "Siloso Beach Resort - Sentosa",
            "subtitle": "51 Imbiah Walk, Sentosa, Singapore",
            "source": "Nominatim",
            "gps_coordinates": {"latitude": 1.255, "longitude": 103.811},
        }]

    adapters = RequestOrchestratorAdapters(
        analyze_message=unused_async,
        make_confirmation=unused_async,
        create_task=unused_async,
        extract_preferences=lambda query: {},
        resolve_itinerary_anchor=resolve_anchor,
    )
    preferences = {
        "location": "Sentosa", "date": "2026-08-03",
        "start_time": "09:00", "end_time": "19:00",
        "timezone": "Asia/Singapore", "budget_mode": "unlimited",
        "style": "sightseeing", "pace": "balanced",
        "hotel_anchor": "Siloso Beach Resort", "anchor_policy": "round_trip",
    }
    resolved = await _resolve_itinerary_anchor_preferences(adapters, preferences)
    confirmation = _itinerary_confirmation(
        "Plan a day from my hotel", {"mode": "itinerary"}, resolved
    )
    assert resolved["resolved_anchors"]["start"]["provider_id"] == "hotel-1"
    assert "_anchor_resolution_error" not in resolved
    assert _itinerary_form_incomplete(confirmation, resolved) is False


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_prefers_direct_anchor_geocoder_over_broad_hotel_discovery(monkeypatch):
    import langgraph_metarec.graphs.generic_graph as generic_graph_module
    import langgraph_metarec.tool_registry as tool_registry_module

    constraints = json.dumps({
        "location": "Sentosa", "date": "2026-08-03",
        "start_time": "09:00", "end_time": "19:00",
        "timezone": "Asia/Singapore", "budget_mode": "unlimited",
        "style": "sightseeing", "pace": "balanced",
        "hotel_anchor": "Soliso Beach Resort", "anchor_policy": "round_trip",
    })
    service, _ = make_service([query_intent_json(), constraints])

    monkeypatch.setattr(
        tool_registry_module,
        "geocode_anchor_candidates",
        lambda anchor_query, destination, max_results=4: [{
            "id": "nominatim:42", "domain": "hotel",
            "title": "Siloso Beach Resort - Sentosa",
            "subtitle": "51 Imbiah Walk, Sentosa, Singapore",
            "source": "Nominatim",
            "gps_coordinates": {"latitude": 1.255, "longitude": 103.811},
        }],
    )

    async def broad_discovery_must_not_run(**kwargs):
        raise AssertionError("broad hotel discovery should not run after direct resolution")

    monkeypatch.setattr(generic_graph_module, "run_generic_domain_graph", broad_discovery_must_not_run)
    result = await service.handle_user_request_async(
        "Plan a day in Sentosa starting from my hotel",
        user_id="u-direct-anchor",
        session_id="c-direct-anchor",
        conversation_history=[],
        itinerary_mode=True,
    )
    preferences = result["confirmation_request"].preferences
    assert preferences["resolved_anchors"]["start"]["provider_id"] == "nominatim:42"
    assert result["confirmation_request"].preference_form["complete"] is True
    assert "couldn't resolve" not in result["confirmation_request"].message.lower()


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_hitl_form_submission_with_empty_field_keeps_extracted_location():
    # A pristine form field arrives as "" — it must not wipe the location the
    # LLM extracted from the original query when the client round-trips the form.
    confirmation_no = json.dumps(
        {"intent": "confirmation_no", "reply": "Let me adjust.", "confidence": 0.9, "preferences": None}
    )
    service, _ = make_service([query_intent_json(), "no usable constraints", confirmation_no])
    first = await service.handle_user_request_async(
        "Plan my day out, please",
        user_id="u-overlay",
        session_id="c-overlay",
        conversation_history=[],
    )
    assert first["preferences"]["location"] == "Chinatown"  # extracted by the intent LLM

    hitl = dict(first["hitl_state"])
    hitl["action"] = "reject"
    hitl["preferences"] = {"location": "", "budget": "< 50 SGD"}  # untouched field + a real edit

    second = await service.handle_user_request_async(
        "Adjust the plan",
        user_id="u-overlay",
        session_id="c-overlay",
        conversation_history=[],
        hitl_state=hitl,
    )

    assert second["type"] == "confirmation"
    assert second["preferences"]["location"] == "Chinatown"  # survived the empty overlay
    assert second["preferences"]["budget"] == "< 50 SGD"


@pytest.mark.backend_unit
def test_itinerary_anchor_missing_helper():
    from langgraph_metarec.graphs.request_orchestrator import _itinerary_anchor_missing

    anchored_route = {"mode": "itinerary", "metadata": {"hotel_anchor_requested": True}}
    assert _itinerary_anchor_missing(anchored_route, {}) is True
    assert _itinerary_anchor_missing(anchored_route, {"hotel_anchor": "  "}) is True
    assert _itinerary_anchor_missing(anchored_route, {"hotel_anchor": "Amara Sanctuary"}) is False
    assert _itinerary_anchor_missing(anchored_route, {"lodging_mode": "none"}) is False
    # Not requested, or not an itinerary route: never gates.
    assert _itinerary_anchor_missing({"mode": "itinerary", "metadata": {}}, {}) is False
    assert _itinerary_anchor_missing({"mode": "multi_domain", "metadata": {"hotel_anchor_requested": True}}, {}) is False
    assert _itinerary_anchor_missing(None, {}) is False


@pytest.mark.backend_unit
def test_explicit_anchor_clear_removes_stale_resolution_without_blank_field_leakage():
    from langgraph_metarec.graphs.request_orchestrator import (
        _apply_preference_clears,
        _merge_hitl_preferences,
    )

    cleared = _apply_preference_clears(
        {
            "location": "Sentosa",
            "hotel_anchor": "Unknown Resort",
            "lodging_mode": "supplied",
            "resolved_anchors": {
                "start": {"query": "Unknown Resort", "provider_id": "old"},
                "end": {"query": "HarbourFront", "provider_id": "end"},
            },
            "_anchor_resolution_attempts": {
                "start": {"fingerprint": "old", "status": "unresolved"},
                "end": {"fingerprint": "end", "status": "resolved"},
            },
            "_anchor_resolution_error": "start",
        },
        ["hotel_anchor", "location", "not_allowed"],
    )

    assert cleared["location"] == "Sentosa"
    assert "hotel_anchor" not in cleared
    assert "lodging_mode" not in cleared
    assert "start" not in cleared["resolved_anchors"]
    assert cleared["resolved_anchors"]["end"]["provider_id"] == "end"
    assert "start" not in cleared["_anchor_resolution_attempts"]
    assert "_anchor_resolution_error" not in cleared

    merged = _merge_hitl_preferences(
        {"hotel_anchor": "Unknown Resort", "lodging_mode": "supplied"},
        {"hotel_anchor": "Unknown Resort", "lodging_mode": "none"},
        ["hotel_anchor"],
    )
    assert merged.get("hotel_anchor") is None
    assert merged["lodging_mode"] == "none"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_unchanged_unresolved_anchor_is_not_resolved_twice():
    from langgraph_metarec.graphs.request_orchestrator import (
        RequestOrchestratorAdapters,
        _itinerary_confirmation,
        _resolve_itinerary_anchor_preferences,
    )

    calls = 0

    async def unused_async(*args, **kwargs):
        return {}

    async def unresolved(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    adapters = RequestOrchestratorAdapters(
        analyze_message=unused_async,
        make_confirmation=unused_async,
        create_task=unused_async,
        extract_preferences=lambda query: {},
        resolve_itinerary_anchor=unresolved,
    )
    preferences = {
        "location": "Sentosa",
        "date": "2026-08-03",
        "start_time": "09:00",
        "end_time": "19:00",
        "timezone": "Asia/Singapore",
        "budget_mode": "unlimited",
        "style": "sightseeing",
        "pace": "balanced",
        "lodging_mode": "supplied",
        "hotel_anchor": "Unknown Resort",
    }

    first = await _resolve_itinerary_anchor_preferences(adapters, preferences)
    second = await _resolve_itinerary_anchor_preferences(adapters, first)
    confirmation = _itinerary_confirmation("Plan my day", {"mode": "itinerary"}, second)

    assert calls == 1
    assert second["_anchor_resolution_error"] == "start"
    assert confirmation["quick_actions"][0]["id"] == "anchor_start_none"
    assert confirmation["quick_actions"][0]["clear_preference_keys"] == ["hotel_anchor"]


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_itinerary_confirm_without_hotel_anchor_reopens_clarification():
    # Server-side enforcement: pressing Confirm while the required hotel anchor
    # is still empty must NOT create a task — it re-opens the clarification
    # (the form's `required` flag alone is only a client-side hint).
    service, fake_client = make_service([query_intent_json(), "no usable constraints"])
    first = await service.handle_user_request_async(
        "Plan my day from my hotel in Sentosa",
        user_id="u-anchor-gate",
        session_id="c-anchor-gate",
        conversation_history=[],
    )
    assert first["type"] == "confirmation"

    hitl = dict(first["hitl_state"])
    hitl["action"] = "confirm"  # confirm submitted without filling hotel_anchor

    second = await service.handle_user_request_async(
        "confirm",
        user_id="u-anchor-gate",
        session_id="c-anchor-gate",
        conversation_history=[],
        hitl_state=hitl,
    )

    assert second["type"] == "confirmation"
    assert "task_id" not in second
    assert "starting hotel" in second["confirmation_request"].message.lower()
    assert second["hitl_state"]["status"] == "awaiting_clarification"
    form = second["confirmation_request"].preference_form
    assert "hotel_anchor" in form["missing_required"]
    # The gate is deterministic: no additional LLM call beyond the first round.
    assert fake_client.chat.completions.calls == 2


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_uses_routing_graph_for_generic_domain_confirmation():
    # A non-restaurant domain now also gets a natural confirmation message
    # (one analyze call + one confirmation-message call).
    service, fake_client = make_service(
        [query_intent_json(), "Sure — looking for a relaxing music playlist. Is that correct?"]
    )

    result = await service.handle_user_request_async(
        "Recommend a relaxing music playlist",
        user_id="u-routing",
        session_id="c-routing",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["domain"] == "music"
    assert result["routing"]["status"] == "ready"
    assert result["routing"]["execution_domain"] == "music"
    assert result["routing"]["tool_tags"] == ["#thing", "#music"]
    # `location` is a generic key now (hotels consume it); an explicitly
    # extracted location passes through and music tools simply ignore it.
    assert result["preferences"] == {
        "domain": "music",
        "query": "Recommend a relaxing music playlist",
        "location": "Chinatown",
    }
    assert "restaurant" not in result["confirmation_request"].message.lower()
    # Round 1 is light: no request-time form (reserved for the refine round); the
    # message plus any quick actions carry the first confirmation.
    assert result["confirmation_request"].preference_form is None
    assert result["hitl_state"]["routing"]["execution_domain"] == "music"
    assert fake_client.chat.completions.calls == 2


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_hotel_query_confirms_with_stay_preferences():
    # Hotel flows through the same generic confirmation path: routing resolves
    # the hotel tags and the extracted stay preferences (destination, stars)
    # survive into the set under review.
    intent_payload = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, let me find a hotel.",
            "confidence": 0.9,
            "preferences": {
                "domain": "hotel",
                "query": "Find a 4-star hotel near Sentosa",
                "location": "Sentosa",
                "stars": "4",
            },
        },
        ensure_ascii=False,
    )
    service, _ = make_service(
        [intent_payload, "Looking for a 4-star hotel near Sentosa — is that correct?"]
    )

    result = await service.handle_user_request_async(
        "Find a 4-star hotel near Sentosa",
        user_id="u-hotel",
        session_id="c-hotel",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["domain"] == "hotel"
    assert result["routing"]["status"] == "ready"
    assert result["routing"]["execution_domain"] == "hotel"
    assert result["routing"]["tool_tags"] == ["#place", "#hotel"]
    prefs = result["confirmation_request"].preferences
    assert prefs["location"] == "Sentosa"
    assert prefs["stars"] == "4"
    assert prefs["domain"] == "hotel"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_hotel_ambiguous_location_requests_clarification():
    intent_payload = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, let me find a hotel.",
            "confidence": 0.9,
            "preferences": {
                "domain": "hotel",
                "query": "Find a hotel in Chinatown",
                "location": "Chinatown",
            },
        },
        ensure_ascii=False,
    )
    service, fake_client = make_service([intent_payload])

    result = await service.handle_user_request_async(
        "Find a hotel in Chinatown",
        user_id="u-hotel-ambiguous",
        session_id="c-hotel-ambiguous",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["intent"] == "confirmation_no"
    assert result["hitl_state"]["status"] == "awaiting_clarification"
    assert result["confirmation_request"].preference_form["domain"] == "hotel"
    assert "city or country" in result["confirmation_request"].message
    assert fake_client.chat.completions.calls == 1


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_hotel_ambiguous_location_uses_profile_context():
    class _ProfileRepo:
        async def get_user_profile(self, _user_id):
            return {"demographics": {"location": "Singapore"}, "metadata": {"domains": {}}}

    intent_payload = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, let me find a hotel.",
            "confidence": 0.9,
            "preferences": {
                "domain": "hotel",
                "query": "Find a hotel in Chinatown",
                "location": "Chinatown",
            },
        },
        ensure_ascii=False,
    )
    service, fake_client = make_service([intent_payload, "Looking for a hotel in Chinatown, Singapore. Is that correct?"])
    service.profile_repository = _ProfileRepo()

    result = await service.handle_user_request_async(
        "Find a hotel in Chinatown",
        user_id="u-hotel-profile-context",
        session_id="c-hotel-profile-context",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["domain"] == "hotel"
    assert result["confirmation_request"].preferences["location"] == "Chinatown, Singapore"
    assert result["confirmation_request"].preference_form is None
    assert fake_client.chat.completions.calls == 2


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_dispatches_hotel_task_to_generic_graph(monkeypatch):
    # A confirmed hotel task executes on the generic domain pipeline with the
    # stay preferences threaded through to the graph (not the restaurant graph).
    import langgraph_metarec.graphs.generic_graph as generic_graph_module
    from langgraph_metarec.graphs.generic_graph import GenericGraphResult

    captured: dict = {}

    async def fake_generic(**kwargs):
        captured.update(kwargs)
        return GenericGraphResult(
            executions=[{"tool": "gmap.hotel.search", "success": True, "output": []}],
            items=[{"id": "h1", "domain": "hotel", "title": "Palm View Hotel", "subtitle": "7 Palm Ave"}],
            metadata={"graph": "generic_domain_graph", "domain": "hotel"},
        )

    monkeypatch.setattr(generic_graph_module, "run_generic_domain_graph", fake_generic)

    service, _ = make_service([])
    preferences = {
        "domain": "hotel",
        "query": "Find a 4-star hotel near Sentosa",
        "location": "Sentosa",
        "stars": "4",
    }
    route = {
        "domain": "hotel",
        "execution_domain": "hotel",
        "mode": "single_domain",
        "status": "ready",
        "tool_tags": ["#place", "#hotel"],
        "domain_tasks": [{"domain": "hotel", "status": "ready", "tool_tags": ["#place", "#hotel"]}],
    }

    await service.process_recommendation_task(
        "task-hotel-1",
        "Find a 4-star hotel near Sentosa",
        preferences,
        user_id="u-hotel",
        session_id="c-hotel-dispatch",
        use_online_agent=False,
        tool_tags=["#place", "#hotel"],
        route=route,
    )

    assert captured["domain"] == "hotel"
    assert captured["tool_tags"] == ["#place", "#hotel"]
    assert captured["preferences"]["location"] == "Sentosa"
    assert captured["preferences"]["stars"] == "4"

    status = service.get_task_status("task-hotel-1", user_id="u-hotel", session_id="c-hotel-dispatch")
    assert status["status"] == "completed"
    result = status["result"]
    items = result.items if hasattr(result, "items") and not isinstance(result, dict) else result["items"]
    assert items[0].title == "Palm View Hotel"
    assert items[0].domain == "hotel"
    assert result.restaurants == []


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_routes_implicit_chinese_music_recommendation_from_llm_semantics():
    intent_payload = json.dumps(
        {
            "intent": "query",
            "reply": "可以，我帮你找几首。",
            "confidence": 0.42,
            "preferences": {
                "domain": "music",
                "artist": "万能青年旅店",
                "query": "万能青年旅店有什么歌好听呀",
            },
        },
        ensure_ascii=False,
    )
    service, _ = make_service([intent_payload, "我会按万能青年旅店来找歌，确认吗？"])

    result = await service.handle_user_request_async(
        "万能青年旅店有什么歌好听呀",
        user_id="u-routing",
        session_id="c-routing-implicit-music",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["domain"] == "music"
    assert result["routing"]["execution_domain"] == "music"
    assert result["preferences"]["artist"] == "万能青年旅店"
    assert result["confirmation_request"].preference_form is None  # round 1: no form


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_keeps_plain_chat_as_chat_with_light_recommendation_prompt():
    chat_payload = json.dumps(
        {
            "intent": "chat",
            "reply": "你好，我在。",
            "confidence": 0.9,
            "preferences": None,
        },
        ensure_ascii=False,
    )
    service, _ = make_service([chat_payload])

    result = await service.handle_user_request_async(
        "你好，最近怎么样",
        user_id="u-routing",
        session_id="c-routing-chat",
        conversation_history=[],
    )

    assert result["type"] == "llm_reply"
    assert result["intent"] == "chat"
    reply = result["llm_reply"]
    for domain_label in ("餐厅", "酒店", "景点", "电影", "音乐", "书籍", "商品"):
        assert domain_label in reply


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generic_confirmation_keeps_generic_preferences_without_restaurant_leakage():
    intent_payload = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, I can help with that.",
            "confidence": 0.9,
            "preferences": {
                "genres": ["science fiction"],
                "restaurant_types": ["casual"],
                "location": "Chinatown",
            },
        },
        ensure_ascii=False,
    )
    service, _ = make_service([intent_payload])

    result = await service.handle_user_request_async(
        "Recommend a science fiction movie",
        user_id="u-routing",
        session_id="c-routing-movie",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["domain"] == "movie"
    # Restaurant-only keys are stripped; location is generic (hotel consumes it)
    # so an explicitly extracted one is kept — movie tools simply ignore it.
    assert result["preferences"] == {
        "genres": ["science fiction"],
        "location": "Chinatown",
        "domain": "movie",
        "query": "Recommend a science fiction movie",
    }
    assert "restaurant_types" not in result["confirmation_request"].preferences
    assert result["confirmation_request"].preference_form is None  # round 1: no form


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_product_confirmation_derives_structured_form_fields_from_query():
    query = "我需要一台不那么贵的iOS测试手机，推荐一下呗"
    intent_payload = json.dumps(
        {
            "intent": "query",
            "reply": "可以，我帮你找。",
            "confidence": 0.9,
            "preferences": {"domain": "product", "query": query},
        },
        ensure_ascii=False,
    )
    service, _ = make_service([intent_payload, "我会帮你找适合 iOS 测试的手机，这样对吗？"])

    result = await service.handle_user_request_async(
        query,
        user_id="u-routing",
        session_id="c-routing-product-form",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert result["domain"] == "product"
    prefs = result["confirmation_request"].preferences
    assert prefs["product"] == "iPhone"
    assert prefs["brand"] == "Apple"
    assert prefs["category"] == "smartphone"
    assert prefs["use_case"] == "iOS testing"
    assert prefs["budget"] == "affordable"
    # Round 1 carries no form; these normalized prefs are what a later refine
    # round's form is pre-filled from.
    assert result["confirmation_request"].preference_form is None


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_new_generic_query_replaces_open_confirmation_domain():
    music_intent = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, I can help with music.",
            "confidence": 0.9,
            "preferences": {"domain": "music", "artist": "Daft Punk", "genres": ["electronic"]},
        },
        ensure_ascii=False,
    )
    movie_intent = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, I can help with a movie.",
            "confidence": 0.9,
            "preferences": {"domain": "movie", "genres": ["science fiction"]},
        },
        ensure_ascii=False,
    )
    service, _ = make_service(
        [
            music_intent,
            "Looking for Daft Punk music. Is that correct?",
            movie_intent,
            "Looking for a science fiction movie. Is that correct?",
        ]
    )

    first = await service.handle_user_request_async(
        "Recommend music by Daft Punk",
        user_id="u-routing",
        session_id="c-routing-switch",
        conversation_history=[],
    )
    assert first["type"] == "confirmation"
    assert first["domain"] == "music"

    second = await service.handle_user_request_async(
        "Recommend a science fiction movie",
        user_id="u-routing",
        session_id="c-routing-switch",
        conversation_history=[],
    )

    assert second["type"] == "confirmation"
    assert second["domain"] == "movie"
    assert second["preferences"]["domain"] == "movie"
    assert second["preferences"]["query"] == "Recommend a science fiction movie"
    assert second["preferences"]["genres"] == ["science fiction"]
    assert "artist" not in second["preferences"]
    assert second["confirmation_request"].preference_form is None  # round 1: no form


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_generic_refinement_overlays_non_restaurant_preferences():
    movie_intent = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, I can help with a movie.",
            "confidence": 0.9,
            "preferences": {"domain": "movie", "genres": ["science fiction"]},
        },
        ensure_ascii=False,
    )
    refine_intent = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, comedy instead.",
            "confidence": 0.9,
            "preferences": {"genres": ["comedy"]},
        },
        ensure_ascii=False,
    )
    service, _ = make_service(
        [
            movie_intent,
            "Looking for a science fiction movie. Is that correct?",
            refine_intent,
            "Looking for a comedy movie. Is that correct?",
        ]
    )

    first = await service.handle_user_request_async(
        "Recommend a science fiction movie",
        user_id="u-routing",
        session_id="c-routing-refine",
        conversation_history=[],
    )
    assert first["type"] == "confirmation"

    refined = await service.handle_user_request_async(
        "Make it comedy instead",
        user_id="u-routing",
        session_id="c-routing-refine",
        conversation_history=[],
    )

    assert refined["type"] == "confirmation"
    assert refined["domain"] == "movie"
    assert refined["preferences"]["genres"] == ["comedy"]
    assert refined["preferences"]["domain"] == "movie"
    assert refined["preferences"]["query"] == "Recommend a science fiction movie"
    assert refined["confirmation_request"].preference_form is None  # in-flow refine: no form


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_stores_restaurant_route_scope_for_confirmed_task():
    service, _ = make_service(
        [
            query_intent_json(),
            "I found your restaurant preferences. Is this correct?",
        ]
    )

    result = await service.handle_user_request_async(
        "Recommend spicy restaurants in Chinatown",
        user_id="u-routing",
        session_id="c-routing",
        conversation_history=[],
    )

    assert result["type"] == "confirmation"
    assert service._get_session_context("u-routing", "c-routing")["context"] == {}
    assert result["hitl_state"]["routing"]["execution_domain"] == "restaurant"
    assert result["hitl_state"]["routing"]["tool_tags"] == ["#place", "#restaurant"]
    assert result["metadata"]["thread_id"] == "u-routing:c-routing:branch-main"


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_returns_graceful_unsupported_reply_for_unknown_route():
    neutral_query_intent = json.dumps(
        {
            "intent": "query",
            "reply": "Sure, I can help with that.",
            "confidence": 0.9,
            "preferences": {
                "restaurant_types": ["any"],
                "flavor_profiles": ["any"],
                "dining_purpose": "any",
                "budget_range": {"min": 20, "max": 60, "currency": "SGD", "per": "person"},
                "location": "any",
            },
        },
        ensure_ascii=False,
    )
    service, fake_client = make_service([neutral_query_intent])

    result = await service.handle_user_request_async(
        "Recommend something nice tonight",
        user_id="u-routing",
        session_id="c-routing-unknown",
        conversation_history=[],
    )

    assert result["type"] == "llm_reply"
    assert result["intent"] == "domain_error"
    assert result["routing"]["status"] == "domain_error"
    # Responds as-is: no clarification HITL loop is opened.
    assert result.get("hitl_state") is None
    # The reply points the user at the supported domains (extendable list).
    reply = result["llm_reply"].lower()
    assert "movies" in reply and "books" in reply and "restaurants" in reply
    assert fake_client.chat.completions.calls == 1


@pytest.mark.backend_unit
def test_supported_domains_phrase_covers_every_executable_domain():
    from langgraph_metarec.graphs.routing_graph import (
        EXECUTABLE_DOMAINS,
        supported_domains,
        supported_domains_phrase,
    )

    assert set(supported_domains()) == set(EXECUTABLE_DOMAINS)
    phrase = supported_domains_phrase()
    for label in ("restaurants", "hotels", "tourist attractions", "movies & TV", "music", "books", "products to shop for"):
        assert label in phrase
    assert ", or " in phrase  # readable list join


@pytest.mark.backend_unit
def test_unsupported_domain_reply_for_known_and_unknown():
    from langgraph_metarec.graphs.request_orchestrator import _unsupported_domain_reply

    travel = _unsupported_domain_reply("travel").lower()
    assert "travel" in travel and "support" in travel and "restaurants" in travel

    unknown = _unsupported_domain_reply("unknown").lower()
    assert "not sure" in unknown and "books" in unknown


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_returns_graceful_unsupported_reply_for_future_domain(monkeypatch):
    # A recognized-but-not-connected domain gets the graceful reply, naming the
    # domain and the supported ones, with no HITL loop. All keyword-mapped
    # domains are connected now, so the classifier is stubbed to a synthetic one.
    import langgraph_metarec.graphs.routing_graph as routing_module

    monkeypatch.setattr(
        routing_module, "classify_domain", lambda query: ("travel", 0.8, "matched travel keywords")
    )
    service, _ = make_service([query_intent_json()])

    result = await service.handle_user_request_async(
        "Plan me a weekend trip",
        user_id="u-routing",
        session_id="c-routing-travel",
        conversation_history=[],
    )

    assert result["type"] == "llm_reply"
    assert result["routing"]["domain"] == "travel"
    assert result.get("hitl_state") is None
    reply = result["llm_reply"].lower()
    assert "travel" in reply
    assert "restaurants" in reply and "movies" in reply
