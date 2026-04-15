from ..state import AgentState
from .utils import graph_node

def button_press(state: AgentState, config):
    last_message = state.get('history')[-1]
    btn, action = last_message.content.split("__")
    
    if action == 'press':
        return {
            'decision': ['yes']
        }
    else:
        return {
            'decision': ['no']
        }

