from typing import Annotated, TypedDict, List, Dict, Any, Union, Literal, Optional
from langchain_core.messages import BaseMessage
from langchain_core.utils._merge import merge_dicts
from langgraph.graph.message import add_messages
from operator import add
from pydantic import BaseModel

class InteractionData(BaseModel):
    status: Literal['pending', 'fulfilled', 'static']
    type: str
    data: Dict[str, Any]

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

def dict_reducer(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    final = {**left}
    for k,v in right.items():
        final[k] = v
    return final


class AgentState(BaseModel):
    # routing
    decision: Optional[str] = None

    # summary data
    language: Optional[str] = None
    title: Optional[str] = None
    timestamp: Optional[str] = None
    updated_at: Optional[str] = None
    
    # conversation state
    model:  Optional[str] = None
    history: Annotated[List[BaseMessage], add_messages]
    interactions: Annotated[Dict[str, InteractionData], dict_reducer] = {}
    preferences: Dict[str, Any] = {}
    tasks: Dict[str, Any] = {}
