# 🚀 MetaRec 部署指南

本指南详细说明如何将MetaRec部署到Hugging Face Spaces。

## 📋 部署前检查清单

### ✅ 已完成的配置

以下文件已经配置好，无需额外修改：

1. ✅ **Dockerfile** - 多阶段构建配置
2. ✅ **MetaRec-backend/main.py** - 添加了静态文件服务和端口配置
3. ✅ **MetaRec-backend/requirements.txt** - 添加了aiofiles依赖
4. ✅ **MetaRec-ui/src/utils/api.ts** - 智能环境检测
5. ✅ **README.md** - HF Spaces元数据

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
   - **Space hardware**: CPU basic (免费) 或根据需要选择
   - **Visibility**: Public 或 Private
3. 点击 "Create Space"

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

在推送到HF之前，可以本地测试：

```bash
# 构建镜像
docker build -t metarec-test .

# 运行容器
docker run -p 7860:7860 metarec-test

# 访问
# 前端: http://localhost:7860
# API: http://localhost:7860/api
# API文档: http://localhost:7860/docs
```

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

**解决方案**：
- 检查main.py中的CORS配置是否包含`"*"`
- 确认前端API配置使用相对路径

### 4. 端口配置问题

确认：
- Dockerfile EXPOSE 7860
- main.py 使用 `port = int(os.getenv("PORT", 7860))`

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

在HF Space设置中：
1. 点击 "Settings"
2. 找到 "Repository secrets"
3. 添加环境变量（如API密钥等）

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

1. **限制CORS来源**
   ```python
   # 在main.py中，将 "*" 改为具体域名
   allow_origins=["https://your-space.hf.space"]
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

