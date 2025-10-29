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
from service import MetaRecService, RecommendationResult, ConfirmationRequest, ThinkingStep

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


# ==================== API数据模型 ====================
# 这些模型用于API请求和响应，与服务层的模型分离

class BudgetRangeAPI(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None
    currency: str = "SGD"
    per: str = "person"


class ConstraintsAPI(BaseModel):
    restaurantTypes: List[str]
    flavorProfiles: List[str]
    diningPurpose: str
    budgetRange: Optional[BudgetRangeAPI] = None
    location: Optional[str] = None


class MetaAPI(BaseModel):
    source: str
    sentAt: str
    uiVersion: str


class RecommendationPayloadAPI(BaseModel):
    query: str
    constraints: ConstraintsAPI
    meta: MetaAPI


class RestaurantAPI(BaseModel):
    id: str
    name: str
    cuisine: Optional[str] = None
    location: Optional[str] = None
    rating: Optional[float] = None
    price: Optional[str] = None
    highlights: Optional[List[str]] = None
    reason: Optional[str] = None
    reference: Optional[str] = None


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
    """API根路径，返回API信息"""
    return {"message": "MetaRec API is running!", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/api/recommend", response_model=RecommendationResponseAPI)
async def get_recommendations_smart(query_data: Dict[str, str]):
    """
    智能推荐接口 - 处理用户输入并智能判断意图
    
    这个接口会自动处理：
    - 意图识别（新查询/确认/拒绝）
    - 偏好提取
    - 确认流程
    
    Args:
        query_data: {"query": "用户查询", "user_id": "用户ID（可选）"}
        
    Returns:
        推荐结果或确认请求
    """
    try:
        query = query_data.get("query", "")
        user_id = query_data.get("user_id", "default")
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # 分析用户意图
        intent = metarec_service.analyze_user_intent(query)
        
        if intent["type"] == "confirmation_yes":
            # 用户确认，创建后台任务以显示thinking process
            if user_id in metarec_service.user_contexts:
                context = metarec_service.user_contexts[user_id]
                preferences = context["preferences"]
                original_query = context.get("original_query", query)
                
                # 清除上下文
                del metarec_service.user_contexts[user_id]
                
                # 创建后台任务
                task_id = metarec_service.create_task(original_query, preferences, user_id)
                
                # 返回thinking step让前端知道任务已创建
                return RecommendationResponseAPI(
                    restaurants=[],
                    thinking_steps=[ThinkingStepAPI(
                        step="start_processing",
                        description="Starting recommendation process...",
                        status="thinking",
                        details=f"Task ID: {task_id}"
                    )],
                    confirmation_request=None
                )
            else:
                # 没有上下文，当作新查询处理
                preferences = metarec_service.extract_preferences_from_query(query, user_id)
                task_id = metarec_service.create_task(query, preferences, user_id)
                
                return RecommendationResponseAPI(
                    restaurants=[],
                    thinking_steps=[ThinkingStepAPI(
                        step="start_processing",
                        description="Starting recommendation process...",
                        status="thinking",
                        details=f"Task ID: {task_id}"
                    )],
                    confirmation_request=None
                )
        
        elif intent["type"] == "confirmation_no":
            # 用户拒绝，返回修改提示
            if user_id in metarec_service.user_contexts:
                del metarec_service.user_contexts[user_id]
            
            return RecommendationResponseAPI(
                restaurants=[],
                thinking_steps=None,
                confirmation_request=ConfirmationRequestAPI(
                    message="I understand you'd like to modify your preferences. Please tell me what you'd like to change or provide more details about what you're looking for.",
                    preferences={},
                    needs_confirmation=True
                )
            )
        
        else:
            # 新查询，需要确认
            preferences = metarec_service.extract_preferences_from_query(query, user_id)
            confirmation = metarec_service.create_confirmation_request(query, preferences, user_id)
            
            return RecommendationResponseAPI(
                restaurants=[],
                thinking_steps=None,
                confirmation_request=ConfirmationRequestAPI(**confirmation.dict())
            )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing recommendation: {str(e)}")


@app.post("/api/recommend-with-constraints", response_model=RecommendationResponseAPI)
async def get_recommendations_with_constraints(payload: RecommendationPayloadAPI):
    """
    使用明确约束条件的推荐接口
    
    这个接口直接接收约束条件，不需要确认流程
    
    Args:
        payload: 包含查询和约束条件的完整payload
        
    Returns:
        推荐结果
    """
    try:
        # 转换API模型到服务层的偏好格式
        preferences = {
            "restaurant_types": payload.constraints.restaurantTypes,
            "flavor_profiles": payload.constraints.flavorProfiles,
            "dining_purpose": payload.constraints.diningPurpose,
            "budget_range": payload.constraints.budgetRange.dict() if payload.constraints.budgetRange else {},
            "location": payload.constraints.location or "any"
        }
        
        # 调用服务层获取推荐
        result = await metarec_service.get_recommendations(
            query=payload.query,
            preferences=preferences,
            user_id="default",
            include_thinking=True
        )
        
        return RecommendationResponseAPI(
            restaurants=[RestaurantAPI(**r.dict()) for r in result.restaurants],
            thinking_steps=[ThinkingStepAPI(**s.dict()) for s in result.thinking_steps] if result.thinking_steps else None,
            confirmation_request=None
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing recommendation: {str(e)}")


@app.post("/api/confirm", response_model=Dict[str, str])
async def confirm_and_start_processing(confirmation_data: Dict[str, Any]):
    """
    确认用户偏好并开始处理任务
    
    Args:
        confirmation_data: {"query": "原始查询", "preferences": {...}}
        
    Returns:
        {"task_id": "任务ID", "message": "消息"}
    """
    try:
        query = confirmation_data.get("query", "")
        preferences = confirmation_data.get("preferences", {})
        user_id = confirmation_data.get("user_id", "default")
        
        # 创建后台任务
        task_id = metarec_service.create_task(query, preferences, user_id)
        
        return {"task_id": task_id, "message": "Task started successfully"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting task: {str(e)}")


@app.get("/api/status/{task_id}", response_model=TaskStatusAPI)
async def get_task_status(task_id: str):
    """
    获取任务状态
    
    Args:
        task_id: 任务ID
        
    Returns:
        任务状态信息
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
        preferences_data: 包含用户偏好的字典
        
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
        用户偏好设置
    """
    try:
        preferences = metarec_service.get_user_preferences(user_id)
        return {
            "user_id": user_id,
            "preferences": preferences
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting user preferences: {str(e)}")


@app.get("/api/restaurants")
async def get_all_restaurants():
    """
    获取所有可用的餐厅（用于调试）
    
    Returns:
        所有餐厅列表
    """
    return {"restaurants": metarec_service.restaurant_data}


@app.post("/api/analyze-intent")
async def analyze_intent(query_data: Dict[str, str]):
    """
    分析用户意图（调试接口）
    
    Args:
        query_data: {"query": "用户输入"}
        
    Returns:
        意图分析结果
    """
    try:
        query = query_data.get("query", "")
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        intent = metarec_service.analyze_user_intent(query)
        return intent
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing intent: {str(e)}")


@app.post("/api/extract-preferences")
async def extract_preferences(query_data: Dict[str, str]):
    """
    从查询中提取偏好（调试接口）
    
    Args:
        query_data: {"query": "用户查询", "user_id": "用户ID（可选）"}
        
    Returns:
        提取的偏好设置
    """
    try:
        query = query_data.get("query", "")
        user_id = query_data.get("user_id", "default")
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        preferences = metarec_service.extract_preferences_from_query(query, user_id)
        return {"preferences": preferences}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error extracting preferences: {str(e)}")


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
    # 使用环境变量PORT，默认7860（Hugging Face Spaces要求）
    # 本地开发可以设置 PORT=8000
    port = int(os.getenv("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
