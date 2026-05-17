from __future__ import annotations

from langgraph_metarec.state import GraphState


def collect_confirm_preferences_node(state: GraphState) -> GraphState:
    """Record the preference collection/confirmation boundary.

    The detailed confirmation state machine still lives in MetaRecService
    for compatibility. This node makes the diagram boundary explicit in
    graph state so routing can consume a normalized recommendation task.
    """
    if state.intent == "query":
        state.preferences = state.preferences or state.pending_preferences or state.current_preferences
        state.needs_confirmation = not state.is_in_query_flow
    elif state.intent in {"confirmation_yes", "confirmation_no"}:
        state.preferences = state.pending_preferences or state.preferences or state.current_preferences
        state.needs_confirmation = state.intent == "confirmation_no"
    else:
        state.needs_confirmation = False

    state.response_payload = {
        "intent": state.intent,
        "preferences": state.preferences,
        "needs_confirmation": state.needs_confirmation,
    }
    return state
