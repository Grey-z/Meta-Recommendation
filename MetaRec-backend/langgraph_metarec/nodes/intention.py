from __future__ import annotations

from typing import Any, Optional

from llm_service import LLMResponse, analyze_user_message
from langgraph_metarec.state import GraphState


async def intent_detection_node(
    state: GraphState,
    *,
    async_client: Any,
    model: Optional[str],
    max_format_retries: int,
) -> tuple[GraphState, LLMResponse]:
    response = await analyze_user_message(
        async_client,
        state.query,
        state.conversation_history,
        state.user_profile,
        is_in_query_flow=state.is_in_query_flow,
        pending_preferences=state.pending_preferences,
        model=model,
        max_format_retries=max_format_retries,
    )
    state.intent = response.intent
    state.intent_confidence = response.confidence
    state.reply = response.reply
    state.preferences = response.preferences
    return state, response

