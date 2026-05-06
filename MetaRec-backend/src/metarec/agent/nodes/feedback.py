from ..state import AgentState
from .utils import graph_node

def handle_interaction(state: AgentState, config, runtime):
    last_message = state.history[-1]
    data = last_message.additional_kwargs
    ref_id = data['ref_id']
    data = data['data']
    old = state.interactions[ref_id]
    if old and old.status == 'pending' and old.type == data['type']:
        return {
            'interactions': {
                ref_id: {
                    'status': 'fulfilled',
                    'type': old.type,
                    'data': data['data'],
                }
            },
        }
    else:
        return {}
