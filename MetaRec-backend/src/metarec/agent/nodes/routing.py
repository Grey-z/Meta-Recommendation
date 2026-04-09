from ..state import AgentState

DEFAULT_INTENT = 'chat'

def intent_router(state: AgentState, config):
    intent_list = state.get('intent', [DEFAULT_INTENT])
    last_intent = intent_list[-1]

    return {
        'decision': [last_intent],
    }

def route_decision(state: AgentState, config):
    return state['decision'][-1]

