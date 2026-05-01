"""
MetaRec FastAPI Application
提供HTTP API接口，调用核心服务层
"""
from dotenv import load_dotenv, find_dotenv
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from client import create_async_client, create_sync_azure_client, create_sync_client, create_async_azure_client
import os
import json
import logging
import sys


# 配置日志系统 - 确保实时输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout)  # 输出到标准输出（控制台）
    ],
    force=True  # 强制重新配置，覆盖之前的配置
)

# 设置 uvicorn 的日志级别
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)

# 导入核心服务
from service import MetaRecService
from conversation_storage import get_storage
from internal.debug.router import create_debug_router

# 导入 LLM 服务
try:
    from llm_service import stream_llm_response
except ImportError:
    stream_llm_response = None

app = FastAPI(title="MetaRec API", version="1.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://*.hf.space",  # Hugging Face Spaces
        "*"  # 允许所有来源（生产环境可根据需要限制）
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# create OpenAI clients
async_client = create_async_client()
llm_model = os.getenv('LLM_MODEL')

try:
    sync_client = create_sync_azure_client()
    summary_model = os.getenv('AZURE_AGENT_SUMMARY_MODEL', 'o4-mini')
    planning_model = os.getenv('AZURE_AGENT_PLANNING_MODEL', 'gpt-4.1')
except Exception as e:
    print('[Warning] Unable to create AzureOpenAI client, falling back to OpenAI client')
    sync_client = create_sync_client()
    summary_model = os.getenv('AGENT_SUMMARY_MODEL')
    planning_model = os.getenv('AGENT_PLANNING_MODEL')

# ==================== 创建服务实例 ====================
# 这是全局服务实例，可以被所有路由使用
metarec_service = MetaRecService(async_client, sync_client, summary_model, planning_model, llm_model)

# 挂载内部 debug 路由（具体可用性由 DEBUG_UI_ENABLED 等环境变量控制）
app.include_router(create_debug_router(lambda: metarec_service))

# ==================== Conversation Preferences 内存缓存 ====================
# 存储格式: {f"{user_id}:{conversation_id}": preferences_dict}
conversation_preferences_cache: Dict[str, Dict[str, Any]] = {}


def get_cache_key(user_id: str, conversation_id: str) -> str:
    """生成缓存键"""
    return f"{user_id}:{conversation_id}"


def load_preferences_from_storage(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """从持久化层加载 preferences 到内存缓存"""
    try:
        storage = get_storage()
        preferences = storage.get_conversation_preferences(user_id, conversation_id)
        if preferences is not None:
            cache_key = get_cache_key(user_id, conversation_id)
            conversation_preferences_cache[cache_key] = preferences
            return preferences
    except Exception as e:
        print(f"Error loading preferences from storage: {e}")
    return None


def get_conversation_preferences_cached(user_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """从内存缓存获取 preferences，如果不存在则从持久化层加载并缓存；会话不存在时返回 None"""
    cache_key = get_cache_key(user_id, conversation_id)
    
    # 优先从内存缓存获取
    if cache_key in conversation_preferences_cache:
        return conversation_preferences_cache[cache_key]
    
    # 缓存未命中，从持久化层加载并缓存
    preferences = load_preferences_from_storage(user_id, conversation_id)
    if preferences is not None:
        return preferences
    
    # 会话不存在
    return None


def update_conversation_preferences_cached(
    user_id: str, 
    conversation_id: str, 
    new_preferences: Dict[str, Any]
) -> bool:
    """更新 preferences：同时更新内存缓存和持久化层"""
    try:
        storage = get_storage()
        cache_key = get_cache_key(user_id, conversation_id)
        
        # 获取当前缓存中的 preferences（如果存在）
        current_preferences = conversation_preferences_cache.get(cache_key, {})
        
        # 更新持久化层
        success = storage.update_conversation_preferences(user_id, conversation_id, new_preferences)
        if not success:
            return False
        
        # 从持久化层获取更新后的完整 preferences（确保数据一致性）
        updated_preferences = storage.get_conversation_preferences(user_id, conversation_id)
        if updated_preferences is not None:
            # 更新内存缓存
            conversation_preferences_cache[cache_key] = updated_preferences
        else:
            # 如果持久化层返回 None，手动合并更新到缓存
            if cache_key not in conversation_preferences_cache:
                conversation_preferences_cache[cache_key] = {}
            
            # 覆盖式更新：只更新有内容的字段
            for key, value in new_preferences.items():
                if value is not None:
                    if isinstance(value, dict):
                        # 对于字典类型，合并更新
                        if key not in conversation_preferences_cache[cache_key]:
                            conversation_preferences_cache[cache_key][key] = {}
                        conversation_preferences_cache[cache_key][key].update(value)
                    elif isinstance(value, list) and len(value) > 0:
                        # 对于列表类型，如果非空则更新
                        conversation_preferences_cache[cache_key][key] = value
                    elif not isinstance(value, (list, dict)):
                        # 对于其他类型，直接更新
                        conversation_preferences_cache[cache_key][key] = value
        
        return True
    except Exception as e:
        print(f"Error updating conversation preferences: {e}")
        return False


# ==================== 静态文件服务配置 ====================
FRONTEND_DIST = (Path(__file__).parent.parent / 'frontend-dist').resolve()

# 启动时检查静态文件目录
def check_frontend_dist():
    """检查前端静态文件目录是否存在"""
    if os.path.exists(FRONTEND_DIST):
        print(f"[INFO] Frontend dist directory found: {FRONTEND_DIST}")
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_path):
            print(f"[INFO] Frontend index.html found: {index_path}")
        else:
            print(f"[WARN] index.html not found in {FRONTEND_DIST}")
        # 列出目录内容
        try:
            files = os.listdir(FRONTEND_DIST)
            print(f"[INFO] Frontend dist contents: {files[:10]}...")  # 只显示前10个
        except Exception as e:
            print(f"[WARN] Error listing frontend dist: {e}")
    else:
        print(f"[WARN] Frontend dist directory not found: {FRONTEND_DIST}")

# 在应用启动时检查
check_frontend_dist()


# ==================== API数据模型 ====================
# 这些模型用于API请求和响应，与服务层的模型分离

class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProcessMessageAPI(StrictBaseModel):
    role: str
    content: str


class ProcessRequestAPI(StrictBaseModel):
    query: str
    user_id: str = "default"
    conversation_history: Optional[List[ProcessMessageAPI]] = None
    conversation_id: Optional[str] = None
    use_online_agent: bool = False


class ProcessStreamRequestAPI(StrictBaseModel):
    query: str
    user_id: str = "default"
    conversation_history: Optional[List[ProcessMessageAPI]] = None
    use_online_agent: bool = False


class HealthResponseAPI(StrictBaseModel):
    status: str
    timestamp: str


class ApiInfoResponseAPI(StrictBaseModel):
    message: str
    version: str


class FrontendConfigResponseAPI(StrictBaseModel):
    googleMapsApiKey: str


class RestaurantAPI(StrictBaseModel):
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


class ThinkingStepAPI(StrictBaseModel):
    step: str
    description: str
    status: str
    details: Optional[str] = None


class ConfirmationRequestAPI(StrictBaseModel):
    message: str
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"additionalProperties": True},
    )
    needs_confirmation: bool = True


class RecommendationResponseAPI(StrictBaseModel):
    restaurants: List[RestaurantAPI]
    thinking_steps: Optional[List[ThinkingStepAPI]] = None
    confirmation_request: Optional[ConfirmationRequestAPI] = None
    llm_reply: Optional[str] = None  # GPT-4 的回复（用于普通对话）
    intent: Optional[str] = None  # 意图类型
    preferences: Optional[Dict[str, Any]] = Field(
        default=None,
        json_schema_extra={"additionalProperties": True},
    )  # 提取的偏好设置（当 intent 为 "query" 时）


class TaskStatusAPI(StrictBaseModel):
    task_id: str
    status: str  # "processing", "completed", "error"
    progress: int  # 0-100
    message: str
    result: Optional[RecommendationResponseAPI] = None
    error: Optional[str] = None


class BudgetRangeInputAPI(StrictBaseModel):
    min: Optional[int] = 20
    max: Optional[int] = 60
    currency: str = "SGD"
    per: str = "person"


class UpdatePreferencesRequestAPI(StrictBaseModel):
    user_id: str = "default"
    restaurantTypes: List[str] = ["any"]
    flavorProfiles: List[str] = ["any"]
    diningPurpose: str = "any"
    budgetRange: BudgetRangeInputAPI = BudgetRangeInputAPI()
    location: str = "any"


class PreferencesResponseAPI(StrictBaseModel):
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"additionalProperties": True},
    )


class UpdatePreferencesResponseAPI(StrictBaseModel):
    message: str
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"additionalProperties": True},
    )


class UserPreferencesResponseAPI(StrictBaseModel):
    user_id: str
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"additionalProperties": True},
    )


class GenericSuccessResponseAPI(StrictBaseModel):
    success: bool
    message: str


# ==================== API路由 ====================

@app.get("/api", response_model=ApiInfoResponseAPI)
async def api_root():
    """
    返回API信息
    
    Returns:
        API基本信息
    """
    return {"message": "MetaRec API is running!", "version": "1.0.0"}


@app.get("/health", response_model=HealthResponseAPI)
async def health_check():
    """
    健康检查
    
    Returns:
        服务健康状态
    """
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/config", response_model=FrontendConfigResponseAPI)
async def get_config():
    """
    获取前端配置信息（包括 Google Maps API Key）
    
    Returns:
        配置信息
    """
    google_maps_api_key = os.getenv("VITE_GOOGLE_MAPS_API_KEY", "")
    return {
        "googleMapsApiKey": google_maps_api_key
    }


@app.post("/api/process", response_model=RecommendationResponseAPI)
async def process_user_request(query_data: ProcessRequestAPI):
    """
    处理用户请求的统一接口
    融合了 LLM 意图识别、偏好提取、确认流程
    
    这个接口会自动处理：
    - 使用 LLM 进行意图识别和生成回复
    - 如果是推荐餐厅请求：触发推荐流程
    - 如果是普通对话：返回 LLM 的回复
    
    Args:
        query_data: {"query": "用户查询", "user_id": "用户ID（可选）", "conversation_history": "对话历史（可选）"}
        
    Returns:
        根据处理结果返回不同的响应：
        - 如果是 LLM 回复：返回 llm_reply 字段
        - 如果是确认请求：返回确认请求对象
        - 如果是任务创建：返回任务ID
        - 如果是修改请求：返回修改提示
    """
    try:
        query = query_data.query
        user_id = query_data.user_id
        conversation_history = query_data.conversation_history
        if conversation_history is not None:
            conversation_history = [msg.model_dump() for msg in conversation_history]
        conversation_id = query_data.conversation_id
        use_online_agent = query_data.use_online_agent
        
        # 添加日志，确认参数接收
        print(f"[API] Received request - use_online_agent: {use_online_agent} (type: {type(use_online_agent)})")
        
        # 调用异步处理函数（使用 LLM 进行意图识别）
        result = await metarec_service.handle_user_request_async(query, user_id, conversation_history, conversation_id, use_online_agent)
        
        # 如果响应包含 preferences 且有 conversation_id，更新 conversation 的 preferences（同时更新内存缓存和持久化层）
        if result.get("preferences") and conversation_id:
            try:
                update_conversation_preferences_cached(user_id, conversation_id, result["preferences"])
            except Exception as e:
                print(f"Warning: Failed to update conversation preferences: {e}")
        
        # 根据处理结果类型返回不同的响应
        if result["type"] == "llm_reply":
            # LLM 的普通对话回复
            # 如果是confirm no的情况（intent为confirmation_no或chat且有preferences），确保返回preferences
            intent = result.get("intent", "chat")
            preferences = result.get("preferences")
            # 如果是confirmation_no但没有preferences，尝试从上下文中获取
            if intent == "confirmation_no" and not preferences:
                session_ctx = metarec_service._get_session_context(user_id, conversation_id)
                if session_ctx.get("context"):
                    preferences = session_ctx["context"].get("preferences")
            
            return RecommendationResponseAPI(
                restaurants=[],
                thinking_steps=None,
                confirmation_request=None,
                llm_reply=result.get("llm_reply", ""),
                intent=intent,
                preferences=preferences
            )
        
        elif result["type"] == "task_created":
            # 任务已创建，返回任务ID和thinking step
            return RecommendationResponseAPI(
                restaurants=[],
                thinking_steps=[ThinkingStepAPI(
                    step="start_processing",
                    description="Starting recommendation process...",
                    status="thinking",
                    details=f"Task ID: {result['task_id']}"
                )],
                confirmation_request=None,
                preferences=result.get("preferences")
            )
        
        elif result["type"] == "confirmation":
            # 需要确认，返回确认请求
            confirmation = result["confirmation_request"]
            # 确保返回intent信息（如果有）
            intent = result.get("intent")
            # 安全地转换 confirmation 对象，确保 preferences 中的列表被正确处理
            confirmation_dict = confirmation.dict()
            # 确保 preferences 中的列表被正确复制（避免引用问题）
            if "preferences" in confirmation_dict:
                preferences = confirmation_dict["preferences"]
                if isinstance(preferences, dict):
                    # 深拷贝 preferences 字典，确保列表被正确复制
                    import copy
                    confirmation_dict["preferences"] = copy.deepcopy(preferences)
            return RecommendationResponseAPI(
                restaurants=[],
                thinking_steps=None,
                confirmation_request=ConfirmationRequestAPI(**confirmation_dict),
                intent=intent,
                preferences=result.get("preferences")
            )
        
        else:  # modify_request
            # 需要修改，返回修改提示
            return RecommendationResponseAPI(
                restaurants=[],
                thinking_steps=None,
                confirmation_request=ConfirmationRequestAPI(
                    message=result["message"],
                    preferences=result.get("preferences", {}),
                    needs_confirmation=True
                ),
                preferences=result.get("preferences")
            )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")


@app.post("/api/process/stream")
async def process_user_request_stream(query_data: ProcessStreamRequestAPI):
    """
    流式处理用户请求（用于逐字显示回复）
    
    Args:
        query_data: {"query": "用户查询", "user_id": "用户ID（可选）", "conversation_history": "对话历史（可选）"}
        
    Returns:
        Server-Sent Events (SSE) 流，逐字返回 GPT-4 的回复
    """
    try:
        query = query_data.query
        user_id = query_data.user_id
        conversation_history = query_data.conversation_history
        if conversation_history is not None:
            conversation_history = [msg.model_dump() for msg in conversation_history]
        
        if stream_llm_response is None:
            raise HTTPException(status_code=500, detail="Stream LLM service not available")
        
        async def generate_stream():
            """生成流式响应"""
            try:
                stream_kwargs = {
                    "conversation_history": conversation_history
                }
                if llm_model:
                    stream_kwargs["model"] = llm_model

                async for chunk in stream_llm_response(async_client, query, **stream_kwargs):
                    # 发送 SSE 格式的数据
                    yield f"data: {json.dumps({'content': chunk, 'done': False})}\n\n"
                
                # 发送完成信号
                yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"
            except Exception as e:
                error_msg = f"Error in stream: {str(e)}"
                yield f"data: {json.dumps({'content': error_msg, 'done': True, 'error': True})}\n\n"
        
        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"  # 禁用 nginx 缓冲
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing stream request: {str(e)}")


@app.get("/api/status/{task_id}", response_model=TaskStatusAPI)
async def get_task_status(
    task_id: str,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
):
    """
    获取任务状态
    前端通过轮询此接口获取任务进度和最终结果
    
    Args:
        task_id: 任务ID
        user_id: 用户ID（可选，提供后更精确查找）
        conversation_id: 会话ID（可选，提供后更精确查找）
        
    Returns:
        任务状态信息，包括：
        - status: "processing" | "completed" | "error"
        - progress: 0-100的进度值
        - message: 当前状态消息
        - result: 推荐结果（任务完成时）
        - error: 错误信息（任务失败时）
    """
    # 如果提供了 user_id，使用精确查找（conversation_id 作为 session_id）
    # 否则在所有 session 中查找（向后兼容）
    task_status = metarec_service.get_task_status(task_id, user_id, conversation_id)
    
    if not task_status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 转换结果格式
    result_api = None
    if task_status.get("result"):
        result = task_status["result"]
        result_api = RecommendationResponseAPI(
            restaurants=[RestaurantAPI(**r.dict()) for r in result.restaurants],
            thinking_steps=[ThinkingStepAPI(**s.dict()) for s in result.thinking_steps] if result.thinking_steps else None,
            confirmation_request=None
        )
    
    return TaskStatusAPI(
        task_id=task_status.get("task_id", task_id),
        status=task_status.get("status", "unknown"),
        progress=task_status.get("progress", 0),
        message=task_status.get("message", ""),
        result=result_api,
        error=task_status.get("error")
    )


@app.post("/api/update-preferences", response_model=UpdatePreferencesResponseAPI)
async def update_preferences_endpoint(preferences_data: UpdatePreferencesRequestAPI):
    """
    更新用户偏好设置
    
    Args:
        preferences_data: 包含用户偏好的字典，格式：
        {
            "user_id": "用户ID（可选，默认'default'）",
            "restaurantTypes": ["casual", "fine-dining"],
            "flavorProfiles": ["spicy", "savory"],
            "diningPurpose": "friends",
            "budgetRange": {"min": 20, "max": 60, "currency": "SGD", "per": "person"},
            "location": "Chinatown"
        }
        
    Returns:
        更新后的偏好设置
    """
    try:
        user_id = preferences_data.user_id
        
        # 验证和标准化偏好数据
        processed_preferences = {
            "restaurant_types": preferences_data.restaurantTypes,
            "flavor_profiles": preferences_data.flavorProfiles,
            "dining_purpose": preferences_data.diningPurpose,
            "budget_range": preferences_data.budgetRange.model_dump(),
            "location": preferences_data.location
        }
        
        # 调用服务层更新偏好（注意：这里没有 session_id，会使用默认 session）
        # 如果需要按 conversation 更新，应该使用 conversation preferences API
        updated_prefs = metarec_service.update_user_preferences(user_id, processed_preferences)
        
        return {
            "message": "Preferences updated successfully",
            "preferences": updated_prefs
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating preferences: {str(e)}")


@app.get("/api/user-preferences/{user_id}", response_model=UserPreferencesResponseAPI)
async def get_user_preferences_endpoint(user_id: str):
    """
    获取用户当前的偏好设置
    
    Args:
        user_id: 用户ID
        
    Returns:
        用户偏好设置，包括：
        - user_id: 用户ID
        - preferences: 偏好设置字典
    """
    try:
        preferences = metarec_service.get_user_preferences(user_id)
        return {
            "user_id": user_id,
            "preferences": preferences
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting user preferences: {str(e)}")


# ==================== 对话历史API ====================

class ConversationSummary(StrictBaseModel):
    """对话摘要（用于列表）"""
    id: str
    title: str
    model: str
    last_message: str
    timestamp: str
    updated_at: str
    message_count: int


class MessageData(StrictBaseModel):
    """消息数据"""
    role: str
    content: str
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        json_schema_extra={"additionalProperties": True},
    )


class ConversationData(StrictBaseModel):
    """完整对话数据"""
    id: str
    user_id: str
    title: str
    model: str
    last_message: str
    timestamp: str
    updated_at: str
    messages: List[MessageData]
    preferences: Dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"additionalProperties": True},
    )


class CreateConversationRequest(StrictBaseModel):
    """创建对话请求"""
    title: Optional[str] = None
    model: str = "RestRec"


class UpdateConversationRequest(StrictBaseModel):
    """更新对话请求"""
    title: Optional[str] = None
    model: Optional[str] = None


class AddMessageRequest(StrictBaseModel):
    """添加消息请求"""
    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        json_schema_extra={"additionalProperties": True},
    )


@app.get("/api/conversations/{user_id}", response_model=List[ConversationSummary])
async def get_all_conversations(user_id: str):
    """
    获取用户的所有对话列表
    
    Args:
        user_id: 用户ID
        
    Returns:
        对话摘要列表
    """
    try:
        storage = get_storage()
        conversations = storage.get_all_conversations(user_id)
        return conversations
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting conversations: {str(e)}")


@app.get("/api/conversations/{user_id}/{conversation_id}", response_model=ConversationData)
async def get_conversation(user_id: str, conversation_id: str):
    """
    获取单个对话的完整信息（包含所有消息）
    
    Args:
        user_id: 用户ID
        conversation_id: 对话ID
        
    Returns:
        完整的对话数据
    """
    try:
        storage = get_storage()
        conversation = storage.get_full_conversation(user_id, conversation_id)
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # 初始化 preferences 缓存（如果不存在）
        cache_key = get_cache_key(user_id, conversation_id)
        if cache_key not in conversation_preferences_cache:
            preferences = conversation.get("preferences", {})
            conversation_preferences_cache[cache_key] = preferences
        
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting conversation: {str(e)}")


@app.post("/api/conversations/{user_id}", response_model=ConversationData)
async def create_conversation(user_id: str, request: CreateConversationRequest):
    """
    创建新对话
    
    Args:
        user_id: 用户ID
        request: 创建对话请求
        
    Returns:
        创建的对话数据
    """
    try:
        storage = get_storage()
        conversation = storage.create_conversation(
            user_id=user_id,
            title=request.title,
            model=request.model
        )
        
        # 初始化内存缓存（新 conversation 的 preferences 为空字典）
        conversation_id = conversation.get("id")
        if conversation_id:
            cache_key = get_cache_key(user_id, conversation_id)
            conversation_preferences_cache[cache_key] = conversation.get("preferences", {})
        
        return conversation
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating conversation: {str(e)}")


@app.put("/api/conversations/{user_id}/{conversation_id}", response_model=ConversationData)
async def update_conversation(
    user_id: str,
    conversation_id: str,
    request: UpdateConversationRequest
):
    """
    更新对话信息（如标题、模型等）
    
    Args:
        user_id: 用户ID
        conversation_id: 对话ID
        request: 更新请求
        
    Returns:
        更新后的对话数据
    """
    try:
        storage = get_storage()
        updates = {}
        
        if request.title is not None:
            updates["title"] = request.title
        if request.model is not None:
            updates["model"] = request.model
        
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        success = storage.update_conversation(user_id, conversation_id, updates)
        
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        conversation = storage.get_full_conversation(user_id, conversation_id)
        return conversation
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating conversation: {str(e)}")


@app.post("/api/conversations/{user_id}/{conversation_id}/messages", response_model=GenericSuccessResponseAPI)
async def add_message(
    user_id: str,
    conversation_id: str,
    request: AddMessageRequest
):
    """
    向对话添加消息
    
    Args:
        user_id: 用户ID
        conversation_id: 对话ID
        request: 添加消息请求
        
    Returns:
        成功状态
    """
    try:
        if request.role not in ["user", "assistant"]:
            raise HTTPException(status_code=400, detail="Role must be 'user' or 'assistant'")
        
        storage = get_storage()
        success = storage.add_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role=request.role,
            content=request.content,
            metadata=request.metadata
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        return {"success": True, "message": "Message added successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding message: {str(e)}")


@app.delete("/api/conversations/{user_id}/{conversation_id}", response_model=GenericSuccessResponseAPI)
async def delete_conversation(user_id: str, conversation_id: str):
    """
    删除对话
    
    Args:
        user_id: 用户ID
        conversation_id: 对话ID
        
    Returns:
        成功状态
    """
    try:
        storage = get_storage()
        success = storage.delete_conversation(user_id, conversation_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        return {"success": True, "message": "Conversation deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting conversation: {str(e)}")


@app.get("/api/conversations/{user_id}/{conversation_id}/preferences", response_model=PreferencesResponseAPI)
async def get_conversation_preferences(user_id: str, conversation_id: str):
    """
    获取对话的偏好设置（优先从内存缓存获取）
    
    Args:
        user_id: 用户ID
        conversation_id: 对话ID
        
    Returns:
        偏好设置字典
    """
    try:
        # 优先从内存缓存获取，未命中时从持久化层加载
        preferences = get_conversation_preferences_cached(user_id, conversation_id)
        
        if preferences is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        return {"preferences": preferences}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting conversation preferences: {str(e)}")


@app.put("/api/conversations/{user_id}/{conversation_id}/preferences", response_model=PreferencesResponseAPI)
async def update_conversation_preferences(
    user_id: str,
    conversation_id: str,
    preferences_data: Dict[str, object]
):
    """
    更新对话的偏好设置（同时更新内存缓存和持久化层）
    
    Args:
        user_id: 用户ID
        conversation_id: 对话ID
        preferences_data: 偏好设置字典
        
    Returns:
        更新后的偏好设置（从内存缓存返回）
    """
    try:
        # 同时更新内存缓存和持久化层
        success = update_conversation_preferences_cached(user_id, conversation_id, preferences_data)
        
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # 从内存缓存获取更新后的 preferences
        updated_preferences = get_conversation_preferences_cached(user_id, conversation_id)
        if updated_preferences is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"preferences": updated_preferences}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating conversation preferences: {str(e)}")


# ==================== 静态文件服务（在所有 API 路由之后）====================

# 挂载静态资源目录
if os.path.exists(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/", include_in_schema=False)
async def serve_root():
    """服务根路径的前端应用"""
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "MetaRec API", "docs": "/docs"}


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    """SPA fallback - 所有未匹配的路由返回 index.html"""
    # 检查是否是静态文件
    file_path = FRONTEND_DIST.joinpath(full_path).resolve()
    
    # 1. Prevent escaping FRONTEND_DIST directory using path traversal i.e. '../' which would otherwise allow user to access arbitrary files on the filesystem
    # TODO: consider logging this to track malicious users?
    if not file_path.is_relative_to(FRONTEND_DIST):
        raise HTTPException(status_code=403, detail="Forbidden")
    
    # 2. check that the requested file exists
    if file_path.is_file(): # checks for existence of file and that the file is a regular file
        return FileResponse(file_path)
    
    # 3. fallback to index page
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    
    # 如果没有前端文件，返回 404
    raise HTTPException(status_code=404, detail="Not found")


# ==================== 启动配置 ====================

if __name__ == "__main__":
    import uvicorn
    # 使用环境变量PORT，默认8000（本地开发）
    # Hugging Face Spaces 可以设置 PORT=7860
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Starting MetaRec API server on http://0.0.0.0:{port}")
    print(f"📖 API docs available at http://localhost:{port}/docs")
    print(f"🌐 Frontend should be available at http://localhost:{port}/")
    print(f"📝 Logging level: INFO - All print() messages will be displayed")
    
    # 配置 uvicorn 日志，确保实时输出
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["default"],
        },
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"level": "INFO"},
        },
    }
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        log_config=log_config,
        log_level="info"
    )
