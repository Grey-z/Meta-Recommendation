from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from llm_service import LLMResponse
from langgraph_metarec.nodes.domain import domain_classification_node
from langgraph_metarec.nodes.intention import intent_detection_node
from langgraph_metarec.state import GraphState


@dataclass
class IntentionGraphResult:
    state: GraphState
    llm_response: LLMResponse


async def run_intention_graph(
    *,
    async_client: Any,
    query: str,
    user_id: str,
    conversation_history: Optional[List[Dict[str, Any]]],
    user_profile: Optional[Dict[str, Any]],
    is_in_query_flow: bool,
    pending_preferences: Optional[Dict[str, Any]],
    current_preferences: Optional[Dict[str, Any]],
    conversation_id: Optional[str],
    message_id: Optional[str],
    branch_id: Optional[str],
    timeline_cursor: Optional[str],
    model: Optional[str],
    max_format_retries: int,
) -> IntentionGraphResult:
    state = GraphState(
        query=query,
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        branch_id=branch_id,
        timeline_cursor=timeline_cursor,
        conversation_history=conversation_history,
        user_profile=user_profile,
        current_preferences=current_preferences,
        pending_preferences=pending_preferences,
        is_in_query_flow=is_in_query_flow,
    )
    state, llm_response = await intent_detection_node(
        state,
        async_client=async_client,
        model=model,
        max_format_retries=max_format_retries,
    )
    state = domain_classification_node(state)
    return IntentionGraphResult(state=state, llm_response=llm_response)

