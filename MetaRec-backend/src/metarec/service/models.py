from pydantic import BaseModel
from typing import (
    List,
    Optional,
    Dict,
    Any,
)
from metarec.legacy.models import *

class RecommendationRequest(BaseModel):
    query_data: Dict[str, Any]

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

