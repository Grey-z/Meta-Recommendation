"""
MetaRec FastAPI Application
提供HTTP API接口，调用核心服务层
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import json

# 导入核心服务
from service import MetaRecService
from conversation_storage import get_storage

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

# ==================== 创建服务实例 ====================
# 这是全局服务实例，可以被所有路由使用
metarec_service = MetaRecService()


# ==================== 静态文件服务配置 ====================
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend-dist")

# 启动时检查静态文件目录
def check_frontend_dist():
    """检查前端静态文件目录是否存在"""
    if os.path.exists(FRONTEND_DIST):
        print(f"✅ Frontend dist directory found: {FRONTEND_DIST}")
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_path):
            print(f"✅ Frontend index.html found: {index_path}")
        else:
            print(f"⚠️  Warning: index.html not found in {FRONTEND_DIST}")
        # 列出目录内容
        try:
            files = os.listdir(FRONTEND_DIST)
            print(f"📁 Frontend dist contents: {files[:10]}...")  # 只显示前10个
        except Exception as e:
            print(f"⚠️  Error listing frontend dist: {e}")
    else:
        print(f"⚠️  Warning: Frontend dist directory not found: {FRONTEND_DIST}")

# 在应用启动时检查
check_frontend_dist()


# ==================== API数据模型 ====================
# 这些模型用于API请求和响应，与服务层的模型分离

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


class TaskStatusAPI(BaseModel):
    task_id: str
    status: str  # "processing", "completed", "error"
    progress: int  # 0-100
    message: str
    result: Optional[RecommendationResponseAPI] = None
    error: Optional[str] = None


# ==================== API路由 ====================

@app.get("/api")
async def api_root():
    """
    返回API信息
    
    Returns:
        API基本信息
    """
    return {"message": "MetaRec API is running!", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """
    健康检查
    
    Returns:
        服务健康状态
    """
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/config")
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


@app.post("/api/process")
async def process_user_request(query_data: Dict[str, Any]):
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
        query = query_data.get("query", "")
        user_id = query_data.get("user_id", "default")
        conversation_history = query_data.get("conversation_history", None)
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # 调用异步处理函数（使用 LLM 进行意图识别）
        result = await metarec_service.handle_user_request_async(query, user_id, conversation_history)
        
        # 根据处理结果类型返回不同的响应
        if result["type"] == "llm_reply":
            # LLM 的普通对话回复
            return RecommendationResponseAPI(
                restaurants=[],
                thinking_steps=None,
                confirmation_request=None,
                llm_reply=result.get("llm_reply", ""),
                intent=result.get("intent", "chat")
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
                confirmation_request=None
            )
        
        elif result["type"] == "confirmation":
            # 需要确认，返回确认请求
            confirmation = result["confirmation_request"]
            return RecommendationResponseAPI(
                restaurants=[],
                thinking_steps=None,
                confirmation_request=ConfirmationRequestAPI(**confirmation.dict())
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
                )
            )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")


@app.post("/api/process/stream")
async def process_user_request_stream(query_data: Dict[str, Any]):
    """
    流式处理用户请求（用于逐字显示回复）
    
    Args:
        query_data: {"query": "用户查询", "user_id": "用户ID（可选）", "conversation_history": "对话历史（可选）"}
        
    Returns:
        Server-Sent Events (SSE) 流，逐字返回 GPT-4 的回复
    """
    try:
        query = query_data.get("query", "")
        user_id = query_data.get("user_id", "default")
        conversation_history = query_data.get("conversation_history", None)
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        if stream_llm_response is None:
            raise HTTPException(status_code=500, detail="Stream LLM service not available")
        
        async def generate_stream():
            """生成流式响应"""
            try:
                async for chunk in stream_llm_response(query, conversation_history):
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
async def get_task_status(task_id: str):
    """
    获取任务状态
    前端通过轮询此接口获取任务进度和最终结果
    
    Args:
        task_id: 任务ID
        
    Returns:
        任务状态信息，包括：
        - status: "processing" | "completed" | "error"
        - progress: 0-100的进度值
        - message: 当前状态消息
        - result: 推荐结果（任务完成时）
        - error: 错误信息（任务失败时）
    """
    task_status = metarec_service.get_task_status(task_id)
    
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


@app.post("/api/update-preferences", response_model=Dict[str, Any])
async def update_preferences_endpoint(preferences_data: Dict[str, Any]):
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
        user_id = preferences_data.get("user_id", "default")
        
        # 验证和标准化偏好数据
        processed_preferences = {
            "restaurant_types": preferences_data.get("restaurantTypes", ["any"]),
            "flavor_profiles": preferences_data.get("flavorProfiles", ["any"]),
            "dining_purpose": preferences_data.get("diningPurpose", "any"),
            "budget_range": preferences_data.get("budgetRange", {
                "min": 20,
                "max": 60,
                "currency": "SGD",
                "per": "person"
            }),
            "location": preferences_data.get("location", "any")
        }
        
        # 调用服务层更新偏好
        updated_prefs = metarec_service.update_user_preferences(user_id, processed_preferences)
        
        return {
            "message": "Preferences updated successfully",
            "preferences": updated_prefs
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating preferences: {str(e)}")


@app.get("/api/user-preferences/{user_id}")
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


@app.post("/api/conversations/{user_id}/{conversation_id}/messages")
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


@app.delete("/api/conversations/{user_id}/{conversation_id}")
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
    file_path = os.path.join(FRONTEND_DIST, full_path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # SPA 路由，返回 index.html
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
    uvicorn.run(app, host="0.0.0.0", port=port)
