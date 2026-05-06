from pydantic import BaseModel, field_validator, ValidationInfo, Field
from typing import (
    List,
    Optional,
    Dict,
    Any,
    Literal,
    Union,
    Annotated,
)
import metarec.legacy.models as legacy

class Limit(BaseModel):
    default: Optional[int] = None

class SelectOption(BaseModel):
    value: str
    label: str

class RangeSpec(BaseModel):
    prefKey: str
    label: str
    lowerLimit: Limit
    upperLimit: Limit
    step: int

class SelectSpec(BaseModel):
    prefKey: str
    label: str
    kind: Literal['RangeSpec']

    options: List[SelectOption] = []
    allowMultiple: bool = False
    allowOther: bool = False

class RangeSpec(BaseModel):
    prefKey: str
    label: str
    kind: Literal['RangeSpec']

    lowerLimit: Limit
    upperLimit: Limit
    allowMultiple: bool = False
    allowOther: bool = False

PreferenceSpec = Union[RangeSpec, SelectSpec]

class TaskStatus(BaseModel):
    task_id: str
    status: Literal['processing', 'completed', 'error']
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    
    @field_validator('progress')
    @classmethod
    def check_progress(cls, v, info: ValidationInfo) -> int:
        if v < 0 or v > 100:
            raise ValueError("progress must be an integer value in the range [0, 100]")
        elif 'status' in info.data and info.data['status'] == 'processing' and v == 100:
            raise ValueError("progress must be an integer value in the range [0, 100) for a processing task")
        elif 'status' in info.data and info.data['status'] == 'completed' and v != 100:
            raise ValueError("progress must be 100 for a completed task")
        return v

    @field_validator('error')
    @classmethod
    def check_error(cls, v, info: ValidationInfo) -> Optional[str]:
        if 'status' in info.data:
            if isinstance(v, str) and info.data['status'] != 'error':
                raise ValueError("error must be null when status != 'error'")
            elif v is None and info.data['status'] == 'error':
                raise ValueError("error must be a string when status=='error'")
        return v

class MessageData(legacy.MessageData):
    """ extended MessageData with id """
    id: Optional[str] = None

class InteractionData(BaseModel):
    status: Literal['fulfilled', 'pending', 'static']
    type: str 
    data: Dict[str, Any]

class InteractionUpdate(BaseModel):
    type: str 
    data: Dict[str, Any]

class ConversationData(legacy.ConversationData):
    """ extended ConversationData interactions """
    messages: List[MessageData]
    interactions: Dict[str, InteractionData] = {}

class RecommendationResponseAPI(legacy.RecommendationResponseAPI):
    """ extended RecommendationResponseAPI """
    messages: List[MessageData]
    interactions: Dict[str, InteractionData] = {}

class TaskStatusAPI(legacy.TaskStatusAPI):
    """ extended task status """
    result: Optional[RecommendationResponseAPI] = None

class QueryData(BaseModel):
    """ based on main.py /api/process endpoint """
    query: str | Dict[str, InteractionUpdate] = ""
    user_id: Annotated[
        str, 
        Field(description="User ID of conversation owning user")
    ] = "default"
    conversation_id: Annotated[
        Optional[str], 
        Field(description="Conversation ID of conversation")
    ] = None
    conversation_history: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(description="Conversation History"),
        Field(deprecated=True),
    ] = None
    use_online_agent: bool = False
    
    @field_validator('query')
    @classmethod
    def check_query(cls, v):
        if isinstance(v, str):
            return v
        elif len(v) != 1:
            raise ValueError("query must be a dictionary containing exactly 1 key.")
        return v
            

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

