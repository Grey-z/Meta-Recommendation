# 🚀 MetaRec 部署指南

本指南详细说明如何将MetaRec部署到Hugging Face Spaces。

## 📋 部署前检查清单

### ✅ 已完成的配置（代码无需改动）

以下文件已经配置好：

1. ✅ **Dockerfile** - 多阶段构建；启动时自动执行 `alembic upgrade head` 再启动服务
2. ✅ **MetaRec-backend/main.py** - 静态文件服务 + SPA 回退 + 端口配置
3. ✅ **MetaRec-backend/requirements.txt** - 后端依赖
4. ✅ **MetaRec-ui/src/utils/api.ts** - 智能环境检测（生产同源调用）
5. ✅ **README.md** - HF Spaces 元数据（含 `sdk: docker`、`app_port: 7860`）

### ⚠️ 部署前必须准备（外部依赖与密钥）

代码无需改动，但 **不配置以下内容应用将无法启动**（启动时的数据库迁移会因缺少
`DATABASE_URL` 而失败）：

- HF Spaces 容器文件系统是 **临时的**（48 小时休眠唤醒、每次重建都会清空），因此
  **数据库必须放在容器之外**。本应用仅支持 PostgreSQL。
- 准备一个 **外部托管 Postgres**（如 [Neon](https://neon.tech) 免费版），复制连接串，
  使用 **纯** `postgresql://USER:PASSWORD@HOST/DB?sslmode=require` 形式
  （不要 `postgresql+psycopg://`，SQLAlchemy 与 LangGraph checkpointer 都接受纯形式）。
- 在 Space 的 **Settings → Variables and secrets** 配置密钥与变量（见 **步骤 2.5**）。
- 容器启动时会自动建表/迁移（`alembic upgrade head`，幂等），无需手动操作。

## 🎯 部署到Hugging Face Spaces

### 步骤 1: 准备Git仓库

```bash
cd /home/jiangnan/data/Meta-Recommendation

# 如果还没有初始化git
git init

# 添加所有文件
git add .

# 提交更改
git commit -m "Configure for Hugging Face Spaces deployment"
```

### 步骤 2: 创建Hugging Face Space

1. 访问 https://huggingface.co/new-space
2. 填写Space信息：
   - **Owner**: 选择你的用户名或组织
   - **Space name**: `metarec` (或你喜欢的名字)
   - **License**: MIT
   - **Select the Space SDK**: ⭐ **Docker** (重要！)
   - **Space hardware**: 选择你的账号可用的硬件；Docker Space 在部分免费计划上可能需要 Pro
   - **Visibility**: Public 或 Private
3. 点击 "Create Space"

### 步骤 2.5: 创建外部数据库并配置密钥

> 建议在首次推送前完成，否则构建后应用会因缺少 `DATABASE_URL` 启动失败。

1. 在 [Neon](https://neon.tech) 创建项目，复制连接串（纯
   `postgresql://…?sslmode=require`）。
2. 进入 Space 的 **Settings → Variables and secrets**。
3. 添加 **Secrets**（运行时，私密）：

   | Secret | 说明 |
   |---|---|
   | `DATABASE_URL` | Neon 连接串 `…?sslmode=require` |
   | `OPENAI_API_KEY` | Azure / OpenAI 密钥 |
   | `AZURE_OPENAI_ENDPOINT` | 如 `https://<resource>.openai.azure.com/` |
   | `AZURE_OPENAI_API_VERSION` | 如 `2024-12-01-preview` |
   | `LLM_MODEL` | 意图 / 对话模型名 |
   | `SERPAPI_KEY` / `SERPAPI_URL` | Google Maps 搜索 |
   | `TIKHUB_API_KEY` | 小红书搜索 |
   | `MAPBOX_ACCESS_TOKEN` | 后端 Mapbox Directions token，用于新加坡外或 OneMap 降级路线；作为 Secret 保存 |
   | `ONEMAP_EMAIL` / `ONEMAP_PASSWORD` | 可选；新加坡步行/公共交通 ETA 与票价 |
   | `METAREC_SESSION_COOKIE_SECURE` | `true`（HF 为 HTTPS） |
   | `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | 设置后启动时 **自动创建** 管理员账号（无需先注册，无需 shell）；密码 >= 8 位 |
   | 可选 | `GROQ_API_KEY`、`API_302_KEY`、`METAREC_ADMIN_EMAILS`、`DEBUG_UI_ENABLED=false`、`LANGGRAPH_STRICT_MSGPACK=true` |

4. 添加 **Variables**（构建期，公开）：

   | Variable | 说明 |
   |---|---|
   | `VITE_MAPBOX_TOKEN` | 前端地图 Mapbox 公开 token（pk.*），构建时打包进前端（建议按 URL 限制） |

   **不要**设置 `VITE_API_BASE_URL`——留空可让前端同源调用后端。

> 管理员引导（推荐，无需 shell）：设置 `SEED_ADMIN_EMAIL` + `SEED_ADMIN_PASSWORD` 两个
> Secret，应用会在启动时 **自动创建** 该管理员账号（无需先注册、无需重启），随后用该账号
> 登录即可访问 `/dashboard`。
> 另一种方式：先在应用内注册某邮箱并填入 `METAREC_ADMIN_EMAILS`，再 **重启一次 Space** 提升。

### 步骤 3: 连接并推送代码

创建Space后，HF会显示推送说明。执行以下命令：

```bash
# 添加HF Space作为远程仓库
git remote add space https://huggingface.co/spaces/<你的用户名>/<space名称>

# 推送代码
git push space main
```

如果你的本地分支是master而不是main：
```bash
git push space master:main
```

如果使用 GitHub Actions 自动部署，请在 GitHub 仓库配置 `HF_SPACE_ID=<owner>/<space-name>` 和具备该 Space 写权限的 `HF_TOKEN`。CI 不会创建新的 Space，只会把通过测试的 `main` 分支提交直接推送到这个已存在的 Space；可选 `HF_SPACE_BRANCH` 用于指定目标分支，默认 `main`。

### 步骤 4: 等待构建

推送后，Hugging Face会自动：
1. 🔨 构建Docker镜像（需要几分钟）
2. 🚀 启动容器
3. 🌐 分配公开URL

你可以在Space页面查看构建日志。

### 步骤 5: 访问应用

构建成功后，访问：
```
https://huggingface.co/spaces/<你的用户名>/<space名称>
```

或者使用简短链接：
```
https://<你的用户名>-<space名称>.hf.space
```

## 🔧 本地测试Docker构建

### 开发环境：一条命令启动前端、后端和PostgreSQL

```bash
docker compose up --build
```

默认服务：
- 前端 Vite: http://localhost:5173
- 后端 FastAPI: http://localhost:8000
- PostgreSQL: localhost:5432

Compose 会设置：
- `DATABASE_URL=postgresql://metarec:metarec@db:5432/metarec?sslmode=disable`
- `METAREC_CHECKPOINTER_BACKEND=postgres`
- `LANGGRAPH_STRICT_MSGPACK=true`

该模式用于本地开发，前端和后端都通过 bind mount 使用当前源码。LangGraph checkpoint 存入 PostgreSQL volume，业务数据文件存储仍保持现状。

如果本机已有 PostgreSQL 占用 `5432`，可以临时改宿主机端口，容器内部连接不变：

```bash
POSTGRES_HOST_PORT=15432 docker compose up --build
```

停止服务：

```bash
docker compose down
```

如需清空本地 PostgreSQL 数据：

```bash
docker compose down -v
```

### 单容器 production-style 构建

在推送到HF之前，可以本地测试：

```bash
# 构建镜像
docker build -t metarec-test .

# 运行容器（容器启动会先跑 alembic 迁移，因此必须提供可达的 DATABASE_URL）
docker run -p 7860:7860 \
  -e DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require" \
  -e OPENAI_API_KEY=... -e AZURE_OPENAI_ENDPOINT=... -e LLM_MODEL=... \
  metarec-test

# 访问
# 前端: http://localhost:7860
# API: http://localhost:7860/api
# API文档: http://localhost:7860/docs
```

> 提示：本地烟雾测试可直接复用上面的 Neon 连接串；若想完全离线，可临时
> `-e METAREC_CHECKPOINTER_BACKEND=memory` 并指向本地 Postgres。

## 🐛 常见问题排查

### 1. 构建失败

**查看日志**：在HF Space页面点击"Building" → 查看详细日志

**常见原因**：
- Node.js版本不兼容 → 检查Dockerfile中的node版本
- Python依赖安装失败 → 检查requirements.txt
- 前端构建失败 → 本地测试`npm run build`

### 2. 应用启动但显示空白页

**检查项**：
- 查看浏览器控制台是否有错误
- 检查静态文件路径是否正确
- 验证API是否可访问：访问 `https://your-space.hf.space/health`

### 3. API请求失败（CORS错误）

单容器部署下前端与后端 **同源**，正常不会出现 CORS 问题。如遇到：
- 确认 **未** 设置 `VITE_API_BASE_URL`（应使用相对路径，同源调用）
- `main.py` 已通过 `allow_origin_regex=r"https://.*\.hf\.space"` 放行 Space 域名，并启用
  `allow_credentials=True`（因此 **不能** 用 `"*"` 通配 origin）

### 4. 端口配置问题

确认：
- Dockerfile `EXPOSE 7860` 且 `ENV PORT=7860`
- README 顶部元数据含 `app_port: 7860`
- main.py 读取 `port = int(os.getenv("PORT", 8000))`，由 Dockerfile 的 `ENV PORT=7860` 覆盖为 7860

### 5. 应用启动失败 / 数据库报错

- 在 **Logs** 中确认 `alembic upgrade head` 是否成功
- 检查 `DATABASE_URL` 是否为纯 `postgresql://…?sslmode=require`（不带 `+psycopg`）
- Neon 免费版闲置会自动挂起，首个请求唤醒约 1 秒，属正常现象

## 📊 监控和日志

### 查看应用日志

在HF Space页面：
1. 点击 "Logs" 标签
2. 查看实时日志输出

### 查看资源使用

在HF Space页面可以看到：
- CPU使用率
- 内存使用
- 请求数量

## 🔄 更新部署

### 方法1: 通过Git推送

```bash
# 修改代码后
git add .
git commit -m "Update: description of changes"
git push space main
```

HF会自动重新构建和部署。

### 方法2: 通过Web界面

1. 在HF Space页面点击 "Files and versions"
2. 直接编辑文件或上传
3. 保存后自动触发重新构建

## 🎨 自定义配置

### 更改端口（不推荐）

HF Spaces要求使用7860端口，但如果需要在其他平台部署：

```bash
# 设置环境变量
export PORT=8000
python MetaRec-backend/main.py
```

### 添加环境变量

完整清单见 **步骤 2.5**。位置：Space → **Settings → Variables and secrets**
（私密用 **Secrets**，构建期公开变量如 `VITE_MAPBOX_TOKEN` 用 **Variables**）。

### 使用自定义域名

HF Spaces Pro支持自定义域名：
1. 升级到Pro账户
2. 在Settings中配置域名

## 💰 成本估算

### 免费Tier
- CPU basic
- 适合演示和测试
- 可能有休眠时间

### 付费Tier
- 更好的性能
- 无休眠
- 更多资源

查看定价：https://huggingface.co/pricing#spaces

## 🔒 安全建议

### 生产部署建议

1. **CORS 来源已收敛**（无需改动）
   ```python
   # main.py 已限定来源：本地 + 正则放行 *.hf.space，并非通配 "*"
   allow_origin_regex=r"https://.*\.hf\.space"
   allow_credentials=True
   ```

2. **添加速率限制**
   ```python
   # 可以使用slowapi库
   pip install slowapi
   ```

3. **使用环境变量管理敏感信息**
   - 不要在代码中硬编码API密钥
   - 使用HF Spaces的Secrets功能

4. **启用日志记录**
   ```python
   import logging
   logging.basicConfig(level=logging.INFO)
   ```

## 📚 进一步阅读

- [HF Spaces Docker文档](https://huggingface.co/docs/hub/spaces-sdks-docker)
- [HF Spaces配置参考](https://huggingface.co/docs/hub/spaces-config-reference)
- [Docker最佳实践](https://docs.docker.com/develop/dev-best-practices/)

## 🆘 获取帮助

遇到问题？
1. 查看HF Spaces文档
2. 检查构建日志
3. 在HF社区论坛提问
4. 提交Issue到项目仓库

---

**部署完成后记得更新README.md中的Space链接！** 🎉
