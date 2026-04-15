from pydantic import BaseModel
from typing import (
    List,
    Optional,
    Dict,
    Any,
    Literal,
)
from metarec.legacy.models import *

class QueryData(BaseModel):
    """ based on main.py /api/process endpoint """
    query: str = ""
    user_id: str = "default"
    conversation_id: Optional[str] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    use_online_agent: bool = False

class RecommendationRequest(BaseModel):
    query_data: QueryData

class HealthResponse(BaseModel):
    status: str
    timestamp: str

class ConfigResponse(BaseModel):
    googleMapsApiKey: str

class VersionResponse(BaseModel):
    message: str
    version: str

class UserPreferencesResponse(BaseModel):
    user_id: str
    preferences: Dict[str, Any] 

class UpdatePreferencesResponse(BaseModel):
    message: str
    preferences: Dict[str, Any] 

class PreferencesResponse(BaseModel):
    preferences: Dict[str, Any] 

class UpdatePreferencesRequest(BaseModel):
    preferences_data: Dict[str, Any]

class UpdateConversationPreferencesRequest(BaseModel):
    preferences_data: Dict[str, Any]

class SuccessResponse(BaseModel):
    success: bool
    message: str

class ChatRequest(BaseModel):
    history: List[str]

class ChatResponse(BaseModel):
    history: List[str]

