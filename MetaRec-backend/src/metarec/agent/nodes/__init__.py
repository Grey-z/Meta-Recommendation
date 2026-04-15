from .utils import graph_node
from ..state import AgentState
from langchain_core.messages import AIMessage 

@graph_node(name="init")
def init_node(state: AgentState, config, runtime):
    return {
        'history': [
            AIMessage(content="Welcome to MetaRec!\nI'm your personal Restaurant Recommender. How can I help you today?")
        ]
    }
