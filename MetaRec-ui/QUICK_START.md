# MetaRec Quick Start Guide

## 🚀 快速启动

### 1. 启动后端服务器
```bash
# 进入后端目录
cd backend

# 安装依赖
pip install -r requirements.txt

# 启动服务器
python main.py
```
服务器将在 `http://localhost:8000` 启动

### 2. 启动前端应用
```bash
# 在项目根目录
npm install
npm run dev
```
应用将在 `http://localhost:5173` 启动

### 3. 测试API
```bash
# 运行测试脚本
python test_api.py
```

## 📋 当前交互操作总结

### 前端操作
1. **用户输入查询** - 在聊天界面输入自然语言查询
2. **选择偏好设置** - 通过UI面板设置餐厅类型、口味等
3. **确认AI理解** - 当AI需要确认时，用户选择"是的，正确"或"重新描述"
4. **查看思考过程** - 观看AI的思考步骤动画
5. **浏览推荐结果** - 查看推荐的餐厅信息

### 后端处理
1. **接收查询请求** - 处理POST /api/recommend
2. **智能偏好提取** - 从自然语言中提取用户偏好
3. **判断是否需要确认** - 决定是否需要用户确认理解
4. **生成确认消息** - 如果需要确认，生成友好的确认消息
5. **模拟思考过程** - 生成AI思考步骤
6. **筛选推荐餐厅** - 根据偏好筛选合适的餐厅
7. **返回结果** - 返回推荐结果和思考过程

### API端点
- `GET /health` - 健康检查
- `GET /` - 根端点
- `POST /api/recommend` - 获取推荐
- `POST /api/confirm` - 确认偏好
- `GET /api/restaurants` - 获取所有餐厅（调试用）

## 🔄 完整交互流程

```
用户输入 → 前端发送请求 → 后端智能分析 → 
需要确认？ → 是：显示确认对话框 → 用户确认 → 
后端生成思考过程 → 前端显示动画 → 显示推荐结果
                ↓
               否：直接生成思考过程 → 前端显示动画 → 显示推荐结果
```

## 🎯 测试用例

### 简单查询（无需确认）
```
输入: "I want some good restaurants"
预期: 直接显示思考过程和推荐结果
```

### 复杂查询（需要确认）
```
输入: "I want a romantic dinner for date night, budget 100-200 SGD, near Marina Bay"
预期: 显示确认对话框 → 用户确认 → 显示思考过程和推荐结果
```

### 口味偏好查询
```
输入: "I want spicy Sichuan food for friends gathering"
预期: 显示确认对话框 → 用户确认 → 显示思考过程和推荐结果
```

## 🛠️ 调试工具

1. **API文档**: `http://localhost:8000/docs` (Swagger UI)
2. **测试脚本**: `python test_api.py`
3. **健康检查**: `curl http://localhost:8000/health`

## 📁 项目结构

```
MetaRec-ui/
├── backend/                 # Python后端
│   ├── main.py             # FastAPI服务器
│   ├── requirements.txt    # Python依赖
│   └── test_api.py         # API测试脚本
├── src/                    # React前端
│   ├── ui/
│   │   ├── App.tsx         # 主应用
│   │   └── Chat.tsx        # 聊天组件
│   ├── utils/
│   │   ├── api.ts          # API调用函数
│   │   └── types.ts        # TypeScript类型
│   └── styles.css          # 样式文件
├── API_DOCUMENTATION.md    # 完整API文档
├── INTERACTION_FLOW.md     # 交互流程说明
└── QUICK_START.md          # 快速启动指南
```

## ⚠️ 常见问题

### 后端启动失败
- 检查Python版本（需要3.8+）
- 确认端口8000未被占用
- 检查依赖是否正确安装

### 前端无法连接后端
- 确认后端服务器正在运行
- 检查CORS配置
- 确认API地址配置正确

### 推荐结果不准确
- 尝试更具体的查询描述
- 使用偏好面板手动设置条件
- 检查餐厅数据库是否完整
