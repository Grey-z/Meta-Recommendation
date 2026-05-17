# MetaRec Backend API

基于Python FastAPI的餐厅推荐系统后端服务。

## 🎯 新架构说明

MetaRec 现在采用**分层架构设计**，使其既可以作为独立的 Web 服务运行，也可以作为 Python 库被其他模块直接调用：

- **服务层 (service.py)**: 核心业务逻辑，可以被任何 Python 模块直接导入和使用
- **API层 (main.py)**: FastAPI HTTP 接口，提供 RESTful API 访问

这种设计让 MetaRec 可以：
- ✅ 作为独立微服务运行
- ✅ 被主应用模块直接调用（无需 HTTP 开销）
- ✅ 与其他 Python 系统无缝集成

## 功能特性

- 🍽️ 智能餐厅推荐
- 🤖 **AI 对话支持（使用免费大模型 API）**
- 🧠 自动意图识别（新查询/确认/拒绝）
- 💬 智能确认流程
- 🔍 多维度筛选（位置、预算、菜系、用餐目的）
- 🌶️ 口味偏好匹配与学习
- 👤 用户偏好持久化
- 💭 思考过程可视化
- 📍 新加坡本地餐厅数据
- 🚀 高性能 FastAPI 框架
- 🔗 CORS 支持前端集成
- 📦 可作为 Python 库集成

## 快速开始

### 方式一：作为 HTTP API 服务运行

#### 1. 安装依赖

推荐使用 `uv` 管理后端环境：

```bash
cd MetaRec-backend
uv sync
```

如果需要保留传统 pip 工作流，也可以继续使用：

```bash
cd MetaRec-backend
pip install -r requirements.txt
```

#### 1.5. 配置免费大模型 API（可选但推荐）

本项目支持使用免费的大模型 API 进行智能对话。推荐使用 **Groq**（完全免费，速度快）。

**快速配置：**
1. 访问 [Groq Console](https://console.groq.com/) 注册账号
2. 获取 API Key
3. 在 `MetaRec-backend` 目录创建 `.env` 文件：
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   LLM_MODEL=llama-3.1-70b-versatile
   ```

**详细配置说明请查看：** [LLM_SETUP.md](./LLM_SETUP.md)

> 💡 **提示**：如果不配置 API Key，系统会使用规则匹配进行意图识别，功能仍然可用，但无法使用 AI 对话功能。

#### 2. 启动服务器

使用 `uv`：

```bash
uv run python main.py
```

或使用 pip/venv 环境：

```bash
python main.py
```

#### 3. 访问API

- **API服务**: http://localhost:8000
- **交互式文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

### 方式二：作为 Python 库直接调用

在你的主模块中直接导入和使用：

```python
from service import create_service
import asyncio

# 创建服务实例
service = create_service()

# 获取推荐
async def main():
    result = await service.get_recommendations(
        query="I want spicy food for dinner",
        user_id="user_123"
    )
    
    for restaurant in result.restaurants:
        print(f"{restaurant.name} - {restaurant.cuisine}")

asyncio.run(main())
```

**查看更多示例**:
```bash
uv run python example_usage.py  # uv 环境
python example_usage.py         # pip/venv 环境
```

**详细文档**: 参见 [SERVICE_API.md](./SERVICE_API.md)

## API 端点

### POST /api/recommend
获取餐厅推荐

**请求体示例**:
```json
{
  "query": "spicy Sichuan for date night near downtown",
  "constraints": {
    "restaurantTypes": ["fine-dining"],
    "flavorProfiles": ["spicy"],
    "diningPurpose": "date-night",
    "budgetRange": {
      "min": 50,
      "max": 150,
      "currency": "SGD",
      "per": "person"
    },
    "location": "Marina Bay"
  },
  "meta": {
    "source": "MetaRec-UI",
    "sentAt": "2024-01-01T12:00:00Z",
    "uiVersion": "0.0.1"
  }
}
```

**响应示例**:
```json
{
  "restaurants": [
    {
      "id": "1",
      "name": "Din Tai Fung",
      "cuisine": "Taiwanese",
      "location": "Orchard",
      "rating": 4.2,
      "price": "$$",
      "highlights": ["Xiao Long Bao", "Noodles", "Family-friendly"],
      "reason": "Perfect for family dining with authentic Taiwanese cuisine",
      "reference": "https://www.dintaifung.com.sg"
    }
  ]
}
```

### GET /api/restaurants
获取所有餐厅数据（调试用）

### GET /health
健康检查

## 数据模型

### Restaurant
- `id`: 餐厅唯一标识
- `name`: 餐厅名称
- `cuisine`: 菜系类型
- `location`: 位置区域
- `rating`: 评分 (1-5)
- `price`: 价格等级 ($, $$, $$$, $$$$)
- `highlights`: 特色标签
- `reason`: 推荐理由
- `reference`: 参考链接

## 推荐算法

系统根据以下因素进行推荐：

1. **位置匹配**: 根据用户指定的区域筛选
2. **预算匹配**: 根据价格等级筛选
3. **用餐目的**: 约会、家庭、商务等场景匹配
4. **口味偏好**: 辣味、甜味等口味特征
5. **评分排序**: 优先推荐高评分餐厅

## 开发说明

### 项目结构
```
backend/
├── service.py           # 核心服务层（业务逻辑）
├── main.py              # FastAPI应用（HTTP API层）
├── example_usage.py     # 使用示例
├── start_server.py      # 服务器启动脚本
├── pyproject.toml       # uv 项目与依赖声明
├── uv.lock              # uv 锁文件
├── requirements.txt     # pip 运行时依赖
├── requirements-dev.txt # pip 测试依赖
├── SERVICE_API.md       # 服务层API文档
└── README.md           # 项目文档
```

### 核心模块说明

#### `service.py` - 核心服务层
封装所有业务逻辑，包含：
- `MetaRecService`: 主服务类
- 意图分析、偏好提取、推荐生成
- 用户偏好管理、确认流程
- 可被任何 Python 模块直接调用

#### `main.py` - HTTP API层
提供 REST API 接口：
- 将 HTTP 请求转发到服务层
- 处理请求/响应的序列化
- CORS 配置和中间件

### 添加新餐厅

**方式一**：使用默认数据（在 `service.py` 中修改）
```python
# 在 MetaRecService._get_default_restaurants() 中添加
```

**方式二**：使用自定义数据源
```python
from service import MetaRecService

# 从数据库或文件加载
custom_restaurants = load_from_database()

# 创建服务实例
service = MetaRecService(restaurant_data=custom_restaurants)
```

### 自定义推荐逻辑

在 `service.py` 中修改以下方法：
- `filter_restaurants()`: 修改餐厅筛选逻辑
- `extract_preferences_from_query()`: 修改偏好提取规则
- `analyze_user_intent()`: 修改意图识别逻辑
- `_calculate_confidence()`: 修改置信度计算

## 技术栈

- **FastAPI**: 现代、快速的Web框架
- **Pydantic**: 数据验证和序列化
- **LangGraph**: 推荐链路状态管理
- **Uvicorn**: ASGI服务器
- **uv**: Python 环境与依赖锁定
- **Python 3.10+**: 编程语言

## 故障排除

### 端口被占用
如果8000端口被占用，可以修改 `start_server.py` 中的端口号。

### CORS错误
确保前端URL在CORS配置中，当前支持：
- http://localhost:5173
- http://127.0.0.1:5173

### 依赖安装问题
推荐先使用 `uv` 的锁文件安装：
```bash
cd MetaRec-backend
uv sync
uv run python -m pytest -q
```

也可以使用传统虚拟环境和 pip：
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest -q
```
