from pydantic import BaseModel
from typing import (
    List, 
    Dict, 
    Any, 
    Optional,
)

# from metarec.legacy.main
class RestaurantAPI(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    area: Optional[str] = None
    cuisine: Optional[str] = None
    type: Optional[str] = None
    location: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    price: Optional[str] = None
    price_per_person_sgd: Optional[str] = None
    distance_or_walk_time: Optional[str] = None
    open_hours_note: Optional[str] = None
    highlights: Optional[List[str]] = None
    flavor_match: Optional[List[str]] = None
    purpose_match: Optional[List[str]] = None
    why: Optional[str] = None
    reason: Optional[str] = None
    reference: Optional[str] = None
    sources: Optional[Dict[str, str]] = None
    phone: Optional[str] = None
    gps_coordinates: Optional[Dict[str, float]] = None


class ThinkingStepAPI(BaseModel):
    step: str
    description: str
    status: str
    details: Optional[str] = None


class ConfirmationRequestAPI(BaseModel):
    message: str
    preferences: Dict[str, Any]
    needs_confirmation: bool = True


class RecommendationResponseAPI(BaseModel):
    restaurants: List[RestaurantAPI]
    thinking_steps: Optional[List[ThinkingStepAPI]] = None
    confirmation_request: Optional[ConfirmationRequestAPI] = None
    llm_reply: Optional[str] = None  # GPT-4 的回复（用于普通对话）
    intent: Optional[str] = None  # 意图类型
    preferences: Optional[Dict[str, Any]] = None  # 提取的偏好设置（当 intent 为 "query" 时）


class TaskStatusAPI(BaseModel):
    task_id: str
    status: str  # "processing", "completed", "error"
    progress: int  # 0-100
    message: str
    result: Optional[RecommendationResponseAPI] = None
    error: Optional[str] = None

# from metarec.legacy.main
class ConversationSummary(BaseModel):
    """对话摘要（用于列表）"""
    id: str
    title: str
    model: str
    last_message: str
    timestamp: str
    updated_at: str
    message_count: int


class MessageData(BaseModel):
    """消息数据"""
    id: str
    role: str
    content: str
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ConversationData(BaseModel):
    """完整对话数据"""
    id: str
    user_id: str
    title: str
    model: str
    last_message: str
    timestamp: str
    updated_at: str
    messages: List[MessageData]


class CreateConversationRequest(BaseModel):
    """创建对话请求"""
    title: Optional[str] = None
    model: str = "RestRec"


class UpdateConversationRequest(BaseModel):
    """更新对话请求"""
    title: Optional[str] = None
    model: Optional[str] = None


class AddMessageRequest(BaseModel):
    """添加消息请求"""
    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = None

# from metarec.legacy.llm_service
class LLMResponse(BaseModel):
    """LLM 响应模型"""
    intent: str  # "query" (推荐餐厅请求) | "chat" (普通对话) | "confirmation_yes" (确认) | "confirmation_no" (拒绝)
    reply: str  # 大模型的回复内容
    confidence: float = 0.8  # 意图识别置信度
    preferences: Optional[Dict[str, Any]] = None  # 偏好设置（当 intent 为 "query" 时）
    profile_updates: Optional[Dict[str, Any]] = None  # 用户画像更新（可选）

# from metarec.legacy.service
class BudgetRange(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None
    currency: str = "SGD"
    per: str = "person"


class Restaurant(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    area: Optional[str] = None
    cuisine: Optional[str] = None
    type: Optional[str] = None  # casual, fine-dining, etc.
    location: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    price: Optional[str] = None  # price range in SGD
    price_per_person_sgd: Optional[str] = None  # e.g., "20-30", "28.80"
    distance_or_walk_time: Optional[str] = None
    open_hours_note: Optional[str] = None
    highlights: Optional[List[str]] = None
    flavor_match: Optional[List[str]] = None
    purpose_match: Optional[List[str]] = None
    why: Optional[str] = None  # reason for recommendation
    reason: Optional[str] = None  # alias for why
    reference: Optional[str] = None
    sources: Optional[Dict[str, str]] = None  # e.g., {"xiaohongshu": "id", "google_maps": "id"}
    phone: Optional[str] = None
    gps_coordinates: Optional[Dict[str, float]] = None  # {"latitude": 1.29, "longitude": 103.85}


class ThinkingStep(BaseModel):
    step: str
    description: str
    status: str  # "thinking", "completed", "error"
    details: Optional[str] = None


class RecommendationResult(BaseModel):
    """推荐结果"""
    restaurants: List[Restaurant]
    thinking_steps: Optional[List[ThinkingStep]] = None
    confidence_score: Optional[float] = None  # 推荐置信度 0-1
    metadata: Optional[Dict[str, Any]] = None  # 额外的元数据


class ConfirmationRequest(BaseModel):
    """确认请求"""
    message: str
    preferences: Dict[str, Any]
    needs_confirmation: bool = True
