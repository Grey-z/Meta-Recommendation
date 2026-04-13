# 多阶段构建 - 前端构建阶段
FROM node:18-slim AS frontend-builder

WORKDIR /app/Metarec-ui

# 接收构建参数（从 Hugging Face Secrets 传入）
ARG VITE_GOOGLE_MAPS_API_KEY
ENV VITE_GOOGLE_MAPS_API_KEY=$VITE_GOOGLE_MAPS_API_KEY

COPY MetaRec-ui/package*.json ./
RUN npm ci
COPY MetaRec-ui/ ./
RUN npm run build
# 验证构建产物是否存在
RUN ls -la dist/ || echo "Build failed - dist directory not found"
RUN test -f dist/index.html || (echo "ERROR: index.html not found in dist" && exit 1)

# Python后端运行环境
FROM python:3.10-slim as backend-builder

WORKDIR /app
RUN python -m pip install --no-cache-dir build

# 复制后端代码
COPY pyproject.toml .
COPY MetaRec-backend/ ./Metarec-backend/

COPY --from=frontend-builder /app/Metarec-ui/dist ./Metarec-ui/dist
RUN python -m build --wheel


FROM python:3.10-slim
WORKDIR /app

COPY --from=backend-builder /app/dist/*.whl .
RUN python -m pip install *.whl && rm *.whl

# 安装Python依赖
#RUN pip install --no-cache-dir -r backend/requirements.txt

#COPY --from=frontend-builder /app/frontend/dist ./frontend-dist/
# 验证静态文件已复制
RUN python -c "import importlib.resources; \
    path = importlib.resources.files('metarec') / 'frontend-dist' / 'index.html'; \
    assert path.is_file(), 'Frontend assets missing from site-packages!'"

# 设置环境变量 PORT (Hugging Face Spaces 要求使用 7860)
ENV PORT=7860

# 暴露端口 7860 (Hugging Face Spaces 要求)
EXPOSE 7860

# 设置工作目录到后端

# 启动FastAPI服务器
CMD ["python", "-m", "metarec.service"]

