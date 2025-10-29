# MetaRec 服务层 API 文档

## 概述

MetaRec 现在采用分层架构设计：
- **服务层 (service.py)**: 核心业务逻辑，可以被任何 Python 模块直接调用
- **API层 (main.py)**: FastAPI HTTP接口，提供RESTful API访问

这种设计使得 MetaRec 既可以作为独立的 Web 服务运行，也可以作为库被其他 Python 模块集成。

## 架构图

```
┌─────────────────────────────────────────────────────┐
│                   主应用模块                          │
│                (Your Main Module)                    │
└────────────────┬────────────────────────────────────┘
                 │
                 │ 直接调用 (Python)
                 │
┌────────────────▼────────────────────────────────────┐
│              MetaRecService                          │
│              (service.py)                            │
│  • 意图分析   • 偏好提取   • 推荐生成                 │
│  • 确认流程   • 思考模拟   • 任务管理                 │
└────────────────┬────────────────────────────────────┘
                 │
                 │ 也可以通过 HTTP
                 │
┌────────────────▼────────────────────────────────────┐
│              FastAPI Layer                           │
│              (main.py)                               │
│         提供 HTTP REST API 接口                       │
└─────────────────────────────────────────────────────┘
```

## 核心类：MetaRecService

### 初始化

```python
from service import MetaRecService, create_service

# 方式1: 使用默认餐厅数据
service = create_service()

# 方式2: 使用自定义餐厅数据
custom_restaurants = [
    {
        "id": "1",
        "name": "My Restaurant",
        "cuisine": "Italian",
        "location": "Downtown",
        "rating": 4.5,
        "price": "$$$",
        "highlights": ["Romantic", "Wine"],
        "reason": "Great for dates",
        "reference": "https://example.com"
    }
]
service = MetaRecService(restaurant_data=custom_restaurants)
```

### 主要方法

#### 1. 完整推荐流程

```python
async def process_user_message(
    message: str,
    user_id: str = "default"
) -> Tuple[Optional[RecommendationResult], Optional[ConfirmationRequest]]
```

**描述**: 处理用户消息的完整流程，自动处理意图识别、确认流程和推荐生成

**参数**:
- `message`: 用户输入的消息
- `user_id`: 用户ID（用于保存偏好和上下文）

**返回**: 
- 返回元组 `(推荐结果, 确认请求)`
- 只有一个不为 None

**示例**:
```python
# 第一次查询 - 需要确认
result, confirmation = await service.process_user_message(
    "I want spicy food for dinner",
    user_id="user_123"
)
if confirmation:
    print(confirmation.message)  # 显示确认提示

# 用户确认
result, _ = await service.process_user_message(
    "Yes, that's correct",
    user_id="user_123"
)
if result:
    for restaurant in result.restaurants:
        print(restaurant.name)
```

#### 2. 直接获取推荐

```python
async def get_recommendations(
    query: str,
    preferences: Optional[Dict[str, Any]] = None,
    user_id: str = "default",
    include_thinking: bool = True
) -> RecommendationResult
```

**描述**: 直接获取推荐，跳过确认流程

**参数**:
- `query`: 用户查询
- `preferences`: 偏好设置（如果为None则自动从query提取）
- `user_id`: 用户ID
- `include_thinking`: 是否包含思考过程

**返回**: `RecommendationResult` 对象

**示例**:
```python
# 快速推荐（无确认）
result = await service.get_recommendations(
    query="Italian restaurant near Marina Bay",
    user_id="user_123",
    include_thinking=False
)

print(f"Found {len(result.restaurants)} restaurants")
print(f"Confidence: {result.confidence_score}")

for restaurant in result.restaurants:
    print(f"{restaurant.name} - {restaurant.cuisine}")
    print(f"Rating: {restaurant.rating}, Price: {restaurant.price}")
```

#### 3. 意图分析

```python
def analyze_user_intent(query: str) -> Dict[str, Any]
```

**描述**: 分析用户意图，判断是新查询、确认还是拒绝

**返回**: 
```python
{
    "type": "new_query" | "confirmation_yes" | "confirmation_no",
    "original_query": str,
    "confidence": float  # 0-1
}
```

**示例**:
```python
intent = service.analyze_user_intent("Yes, that's correct")
# {'type': 'confirmation_yes', 'original_query': '...', 'confidence': 0.9}

intent = service.analyze_user_intent("I want spicy Korean food")
# {'type': 'new_query', 'original_query': '...', 'confidence': 0.85}
```

#### 4. 偏好提取

```python
def extract_preferences_from_query(
    query: str,
    user_id: str = "default"
) -> Dict[str, Any]
```

**描述**: 从用户查询中智能提取偏好设置

**返回**:
```python
{
    "restaurant_types": List[str],      # ["casual", "fine-dining", ...]
    "flavor_profiles": List[str],       # ["spicy", "savory", ...]
    "dining_purpose": str,              # "date-night", "family", ...
    "budget_range": {
        "min": int,
        "max": int,
        "currency": "SGD",
        "per": "person"
    },
    "location": str                     # "Marina Bay", "Orchard", ...
}
```

**示例**:
```python
preferences = service.extract_preferences_from_query(
    "I want romantic fine dining under 100 SGD in Marina Bay"
)
# 提取结果:
# {
#     "restaurant_types": ["fine-dining"],
#     "flavor_profiles": ["any"],
#     "dining_purpose": "date-night",
#     "budget_range": {"min": None, "max": 100, ...},
#     "location": "Marina Bay"
# }
```

#### 5. 偏好管理

```python
# 获取用户偏好
def get_user_preferences(user_id: str = "default") -> Dict[str, Any]

# 更新用户偏好
def update_user_preferences(
    user_id: str,
    preferences: Dict[str, Any]
) -> Dict[str, Any]
```

**示例**:
```python
# 获取当前偏好
current_prefs = service.get_user_preferences("user_123")

# 更新偏好
new_prefs = {
    "restaurant_types": ["fine-dining"],
    "flavor_profiles": ["spicy"],
    "dining_purpose": "date-night",
    "budget_range": {"min": 50, "max": 100},
    "location": "Marina Bay"
}
updated = service.update_user_preferences("user_123", new_prefs)
```

#### 6. 确认流程

```python
def create_confirmation_request(
    query: str,
    preferences: Dict[str, Any],
    user_id: str = "default"
) -> ConfirmationRequest
```

**描述**: 创建确认请求，用于向用户确认提取的偏好

**示例**:
```python
preferences = service.extract_preferences_from_query(query, user_id)
confirmation = service.create_confirmation_request(query, preferences, user_id)

print(confirmation.message)
# "Based on your query '...', I understand you want:
#  • Restaurant Type: Fine Dining
#  • Flavor Profile: Spicy
#  • Dining Purpose: Date Night
#  ..."
```

#### 7. 异步任务管理

```python
# 创建后台任务
def create_task(
    query: str,
    preferences: Dict[str, Any],
    user_id: str = "default"
) -> str  # 返回 task_id

# 获取任务状态
def get_task_status(task_id: str) -> Optional[Dict[str, Any]]
```

**示例**:
```python
# 创建任务（后台执行）
task_id = service.create_task(query, preferences, "user_123")

# 轮询任务状态
while True:
    status = service.get_task_status(task_id)
    print(f"Progress: {status['progress']}%")
    
    if status['status'] == 'completed':
        result = status['result']
        print(f"Found {len(result.restaurants)} restaurants")
        break
    
    await asyncio.sleep(1)
```

## 数据模型

### RecommendationResult

```python
class RecommendationResult:
    restaurants: List[Restaurant]           # 推荐的餐厅列表
    thinking_steps: Optional[List[ThinkingStep]]  # 思考过程
    confidence_score: Optional[float]       # 置信度 (0-1)
    metadata: Optional[Dict[str, Any]]      # 元数据
```

### Restaurant

```python
class Restaurant:
    id: str
    name: str
    cuisine: Optional[str]
    location: Optional[str]
    rating: Optional[float]
    price: Optional[str]  # "$", "$$", "$$$", "$$$$"
    highlights: Optional[List[str]]
    reason: Optional[str]
    reference: Optional[str]
```

### ConfirmationRequest

```python
class ConfirmationRequest:
    message: str                    # 确认提示消息
    preferences: Dict[str, Any]     # 提取的偏好
    needs_confirmation: bool        # 是否需要确认
```

### ThinkingStep

```python
class ThinkingStep:
    step: str                   # 步骤标识
    description: str            # 步骤描述
    status: str                 # "thinking", "completed", "error"
    details: Optional[str]      # 详细信息
```

## 集成示例

### 在主模块中集成

```python
from service import create_service

class YourMainModule:
    def __init__(self):
        # 初始化推荐服务
        self.rec_service = create_service()
    
    async def handle_user_input(self, user_message: str, user_id: str):
        """处理用户输入"""
        # 使用完整流程（带确认）
        result, confirmation = await self.rec_service.process_user_message(
            user_message,
            user_id
        )
        
        if confirmation:
            # 需要用户确认
            return self.show_confirmation(confirmation)
        
        if result:
            # 返回推荐结果
            return self.show_recommendations(result)
    
    async def quick_recommend(self, query: str, user_id: str):
        """快速推荐（无确认）"""
        result = await self.rec_service.get_recommendations(
            query=query,
            user_id=user_id,
            include_thinking=False
        )
        return result
    
    def analyze_input(self, text: str):
        """分析用户输入"""
        intent = self.rec_service.analyze_user_intent(text)
        preferences = self.rec_service.extract_preferences_from_query(text)
        return intent, preferences
```

### 作为微服务集成

```python
# 你的主应用
from service import MetaRecService
import asyncio

class RecommendationEngine:
    def __init__(self, custom_restaurant_db):
        # 使用自定义数据库
        self.service = MetaRecService(restaurant_data=custom_restaurant_db)
    
    async def get_recommendations_for_user(self, user_profile):
        """根据用户档案生成推荐"""
        # 构建查询
        query = self.build_query_from_profile(user_profile)
        
        # 获取推荐
        result = await self.service.get_recommendations(
            query=query,
            user_id=user_profile['id'],
            include_thinking=True
        )
        
        # 记录到数据库
        self.save_recommendations(user_profile['id'], result)
        
        return result
    
    def update_user_preferences_from_feedback(self, user_id, feedback):
        """根据反馈更新用户偏好"""
        new_prefs = self.extract_prefs_from_feedback(feedback)
        self.service.update_user_preferences(user_id, new_prefs)
```

## HTTP API 接口

如果需要通过 HTTP 访问服务，可以使用 `main.py` 提供的 REST API。

### 主要端点

#### POST /api/recommend
智能推荐接口（带意图识别和确认流程）

```bash
curl -X POST http://localhost:8000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "I want spicy food for dinner", "user_id": "user_123"}'
```

#### POST /api/recommend-with-constraints
直接推荐接口（使用明确的约束条件）

```bash
curl -X POST http://localhost:8000/api/recommend-with-constraints \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Recommend restaurants",
    "constraints": {
      "restaurantTypes": ["fine-dining"],
      "flavorProfiles": ["spicy"],
      "diningPurpose": "date-night",
      "budgetRange": {"min": 50, "max": 100},
      "location": "Marina Bay"
    },
    "meta": {
      "source": "mobile-app",
      "sentAt": "2024-01-01T12:00:00Z",
      "uiVersion": "1.0.0"
    }
  }'
```

#### GET /api/user-preferences/{user_id}
获取用户偏好

```bash
curl http://localhost:8000/api/user-preferences/user_123
```

#### POST /api/update-preferences
更新用户偏好

```bash
curl -X POST http://localhost:8000/api/update-preferences \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "restaurantTypes": ["fine-dining"],
    "flavorProfiles": ["spicy"],
    "diningPurpose": "date-night"
  }'
```

## 最佳实践

### 1. 用户上下文管理

```python
# 为每个用户维护独立的上下文
async def process_conversation(user_id: str, messages: List[str]):
    service = create_service()
    
    for message in messages:
        result, confirmation = await service.process_user_message(
            message,
            user_id  # 使用唯一的user_id
        )
        
        if confirmation:
            # 显示确认
            print(confirmation.message)
        elif result:
            # 显示结果
            print(f"Found {len(result.restaurants)} restaurants")
```

### 2. 性能优化

```python
# 跳过思考过程以提高速度
result = await service.get_recommendations(
    query=query,
    include_thinking=False  # 不包含思考步骤
)

# 使用异步任务处理长时间操作
task_id = service.create_task(query, preferences, user_id)
# 稍后检查结果
status = service.get_task_status(task_id)
```

### 3. 自定义数据源

```python
# 从数据库加载餐厅数据
def load_restaurants_from_db():
    # 你的数据库查询逻辑
    return db.query(Restaurant).all()

# 创建服务时传入自定义数据
service = MetaRecService(restaurant_data=load_restaurants_from_db())
```

### 4. 错误处理

```python
try:
    result = await service.get_recommendations(query, user_id=user_id)
except Exception as e:
    print(f"Recommendation error: {e}")
    # 返回默认推荐或错误消息
```

## 运行示例

查看 `example_usage.py` 获取完整的使用示例：

```bash
cd backend
python example_usage.py
```

这将运行所有示例，展示各种使用场景。

## 总结

MetaRec 服务层提供了：

✅ **灵活集成**: 可作为 Python 库或 HTTP API 使用  
✅ **智能分析**: 自动意图识别和偏好提取  
✅ **确认流程**: 可选的用户确认机制  
✅ **用户管理**: 持久化用户偏好  
✅ **异步支持**: 支持后台任务处理  
✅ **可扩展**: 支持自定义餐厅数据源  
✅ **类型安全**: 使用 Pydantic 模型

根据你的需求选择合适的集成方式！


