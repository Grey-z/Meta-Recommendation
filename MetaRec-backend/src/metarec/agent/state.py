from typing import Annotated, TypedDict, List, Dict, Any, Union
from langchain_core.messages import BaseMessage
from langchain_core.utils._merge import merge_dicts
from langgraph.graph.message import add_messages
from operator import add

def dict_update_reducer(old: Dict[str, Any], update: Dict[str, Any]):
    final = {
        **old,
    }
    for tool_call_id, value in update.items():
        if tool_call_id in old:
            final[tool_call_id] = {
                **final[tool_call_id],
                **value
            }
        else:
            final[tool_call_id] = value
    return final

def queue_reducer(current: list, update: list) -> list:
    # Logic to append new tasks or 'pop' finished ones
    new_state = list(current) if current else []
    id_key = 'tool_call_id'
    for item in update:
        if item.get("_action") == "pop":
            new_state = [i for i in new_state if i.get(id_key) != item[id_key]]
        else:
            new_state.append(item)
    return new_state
    
class AgentState(TypedDict):
    title: str
    model:  str
    timestamp: str
    updated_at: str
    # settings?
    language: str

    # add ensures that values are appended
    intent: Annotated[List[str], add]
    tasks: List[Dict[str, Any]]

    # message history
    # `add_message` ensures that returned values are appended instead of overwriting
    history: Annotated[List[BaseMessage], add_messages]
    
    # routing decisions
    # add ensures that values are appended
    # when using decisions during routing, use the last value
    decision: Annotated[List[str], add]

    # recommendation state
    domain: str
    preferences: Dict[str, Any]
    required_preferences: List[str]
    missing_preferences: List[str]

    tool_plan: Annotated[Dict[str, Any], dict_update_reducer]
    tool_queue: Annotated[list, queue_reducer]
    search_results: List[Any]
