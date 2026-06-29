import json

import pytest

from conftest import make_service, query_intent_json
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
async def test_routing_graph_future_single_domain_does_not_execute_restaurant():
    route = await run_routing_graph(query="Recommend a hotel for tonight", intent="query")

    assert route.domain == "hotel"
    assert route.execution_domain is None
    assert route.status == "future_domain"
    assert route.tool_tags == ["#place", "#hotel"]
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
def test_tool_tags_for_domain_normalizes_tags():
    assert tool_tags_for_domain("hotel") == ["#place", "#hotel"]


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
    assert result["preferences"] == {
        "domain": "music",
        "query": "Recommend a relaxing music playlist",
    }
    assert "restaurant" not in result["confirmation_request"].message.lower()
    # The request-time preference form is attached for the music domain too.
    assert result["confirmation_request"].preference_form["domain"] == "music"
    assert result["hitl_state"]["routing"]["execution_domain"] == "music"
    assert fake_client.chat.completions.calls == 2


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
    assert result["confirmation_request"].preference_form["domain"] == "music"


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
    assert "推荐餐厅、电影、音乐、书籍或商品" in result["llm_reply"]


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
    assert result["preferences"] == {
        "genres": ["science fiction"],
        "domain": "movie",
        "query": "Recommend a science fiction movie",
    }
    assert "restaurant_types" not in result["confirmation_request"].preferences
    assert "location" not in result["confirmation_request"].preferences
    assert result["confirmation_request"].preference_form["missing_required"] == []


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
    assert second["confirmation_request"].preference_form["domain"] == "movie"


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
    assert refined["confirmation_request"].preference_form["missing_required"] == []


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
    for label in ("restaurants", "movies & TV", "music", "books", "products to shop for"):
        assert label in phrase
    assert ", or " in phrase  # readable list join


@pytest.mark.backend_unit
def test_unsupported_domain_reply_for_known_and_unknown():
    from langgraph_metarec.graphs.request_orchestrator import _unsupported_domain_reply

    hotel = _unsupported_domain_reply("hotel").lower()
    assert "hotel" in hotel and "support" in hotel and "restaurants" in hotel

    unknown = _unsupported_domain_reply("unknown").lower()
    assert "not sure" in unknown and "books" in unknown


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_service_returns_graceful_unsupported_reply_for_future_domain():
    # A recognized-but-not-connected domain (hotel) gets the same graceful reply,
    # naming the domain and the supported ones, with no HITL loop.
    service, _ = make_service([query_intent_json()])

    result = await service.handle_user_request_async(
        "Recommend a hotel for tonight",
        user_id="u-routing",
        session_id="c-routing-hotel",
        conversation_history=[],
    )

    assert result["type"] == "llm_reply"
    assert result["routing"]["domain"] == "hotel"
    assert result.get("hitl_state") is None
    reply = result["llm_reply"].lower()
    assert "hotel" in reply
    assert "restaurants" in reply and "movies" in reply
