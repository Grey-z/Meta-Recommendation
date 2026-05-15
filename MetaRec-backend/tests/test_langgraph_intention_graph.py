import pytest

from conftest import FakeAsyncClient, query_intent_json
from langgraph_metarec.graphs.intention_graph import run_intention_graph


@pytest.mark.backend_unit
@pytest.mark.asyncio
async def test_intention_graph_detects_intent_and_domain():
    result = await run_intention_graph(
        async_client=FakeAsyncClient([query_intent_json()]),
        query="Please recommend spicy restaurants in Chinatown",
        user_id="u-1",
        conversation_history=[],
        user_profile=None,
        is_in_query_flow=False,
        pending_preferences=None,
        current_preferences=None,
        conversation_id="c-1",
        message_id="m-1",
        branch_id="b-1",
        timeline_cursor=None,
        model="fake-model",
        max_format_retries=0,
    )

    assert result.llm_response.intent == "query"
    assert result.state.intent == "query"
    assert result.state.domain == "restaurant"
    assert result.state.message_id == "m-1"
    assert result.state.branch_id == "b-1"

