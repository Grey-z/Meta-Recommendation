"""
MetaRec FastAPI Application
提供HTTP API接口，调用核心服务层
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import os

# 导入核心服务
from service import MetaRecService

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


@app.post("/api/process")
async def process_user_request(query_data: Dict[str, Any]):
    """
    处理用户请求的统一接口
    融合了意图识别、偏好提取、确认流程
    
    这个接口会自动处理：
    - 意图识别（新查询/确认/拒绝）
    - 偏好提取（如果是新查询）
    - 确认流程（如果需要）
    - 任务创建（如果用户确认）
    
    Args:
        query_data: {"query": "用户查询", "user_id": "用户ID（可选）"}
        
    Returns:
        根据处理结果返回不同的响应：
        - 如果是确认请求：返回确认请求对象
        - 如果是任务创建：返回任务ID
        - 如果是修改请求：返回修改提示
    """
    try:
        query = query_data.get("query", "")
        user_id = query_data.get("user_id", "default")
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # 调用统一处理函数（融合了意图识别、偏好提取、确认流程）
        result = metarec_service.handle_user_request(query, user_id)
        
        # 根据处理结果类型返回不同的响应
        if result["type"] == "task_created":
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
    port = int(os.getenv("PORT", 7860))  # 默认改为7860，符合HF Spaces要求
    print(f"🚀 Starting MetaRec API server on http://0.0.0.0:{port}")
    print(f"📖 API docs available at http://localhost:{port}/docs")
    print(f"🌐 Frontend should be available at http://localhost:{port}/")
    uvicorn.run(app, host="0.0.0.0", port=port)
