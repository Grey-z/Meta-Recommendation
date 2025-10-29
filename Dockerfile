# 多阶段构建 - 前端构建阶段
FROM node:18-slim AS frontend-builder

WORKDIR /app/frontend
COPY MetaRec-ui/package*.json ./
RUN npm ci
COPY MetaRec-ui/ ./
RUN npm run build

# Python后端运行环境
FROM python:3.10-slim

WORKDIR /app

# 复制后端代码
COPY MetaRec-backend/ ./backend/

# 安装Python依赖
RUN pip install --no-cache-dir -r backend/requirements.txt

# 从前端构建阶段复制静态文件
COPY --from=frontend-builder /app/frontend/dist ./frontend-dist/

# 暴露端口 7860 (Hugging Face Spaces 要求)
EXPOSE 7860

# 设置工作目录到后端
WORKDIR /app/backend

# 启动FastAPI服务器
CMD ["python", "main.py"]

