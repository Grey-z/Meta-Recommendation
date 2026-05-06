from .utils import graph_node
from ..state import AgentState
from langchain_core.messages import AIMessage, HumanMessage, ChatMessage

@graph_node(name="init")
def init_node(state: AgentState, config, runtime):
    return {
        'history': [
            AIMessage(content="Welcome to MetaRec!\nI'm your personal Restaurant Recommender. How can I help you today?")
        ]
    }

@graph_node(name="on_input")
def input_node(state: AgentState, config, runtime):
    last_message = state.history[-1]
    
    if isinstance(last_message, HumanMessage):
        decision = 'human_message'
    elif isinstance(last_message, ChatMessage) and last_message.role == 'interaction':
        decision = 'interaction'
    else:
        decision = 'error'

    return {
        'decision': decision,
    }
