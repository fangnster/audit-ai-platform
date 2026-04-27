# AI Agent 移民律师协作平台

> 多租户 SaaS 平台，基于 AI Agent 辅助移民律师完成 EB-1A 等签证文案的撰写。

---

## 当前功能范围

- 律师注册时登记律所/公司，个人信息可维护联系电话和公司/律所名称；公司/律所当前只作为用户资料展示和编辑，不参与业务权限。
- 案件支持状态流转、客户姓名/邮箱/电话维护、搜索、排序、分页、软删除、恢复和后台管理；客户邮箱或电话至少填写一个。
- 文档上传后由律师手动触发后台解析，支持内置和自定义文件类型，包括原创成果；解析弹窗支持知识库检索和提示词模板；同一文件解析中会阻止重复触发。
- 一篇文档可抽取多条事实；事实可确认、编辑、翻译、删除、提出异议并基于异议后台重解析；同一事实重解析中会阻止重复触发。
- 知识库只按当前律师本人筛选，检索仅依靠标题和标签；解析/重解析只使用提示词模板和 Agent 策略，文案生成/AI 重写可使用全部知识库类型。
- Agent 文案生成支持跨事实、跨知识库材料组织内容，并统一清理模型输出中的 `<think>` 标签；远端请求已加入输入预算、缓存、任务去重、超时释放和失败记录等保护。
- 案件内提供独立「Agent 运行记录」，按文件解析和重解析、事实重解析、文案生成和 AI 重写分类展示输入、结果、诊断、错误和可读上下文。
- 顶部告警栏支持成功/失败历史查询；设置页可按类别分别控制弹出和历史记录，历史名称优先显示原始文件名、事实内容、文案标题等可追踪源对象。
- 任务中心支持跨案件待办；案件内「案件任务」支持新建、状态变更、标记完成、删除和恢复。
- 系统后台支持概览、用户/案件搜索分页排序、用户启停、管理员授权、重置密码、删除用户和案件。
- 前端支持明亮版与经典暗色版两套主题，律师可在设置中自行选择。

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.11 + FastAPI + Celery |
| 数据库 | PostgreSQL 16 |
| 缓存/队列 | Redis 7 |
| 对象存储 | MinIO（本地）/ Cloudflare R2（云端） |
| LLM | MiniMax / OpenAI Compatible / Claude / Gemini / Ollama（可切换） |
| 前端 | React 18 + TypeScript + Vite |
| 容器化 | Docker + Docker Compose |

---

## 文档索引

- [AI Agent 移民律师协作平台 V1.2 需求说明书](AI%20Agent%20移民律师协作平台%20V1.md)
- [产品需求文档：当前实现版](docs/product_requirements.md)
- [技术实现文档](docs/implementation.md)
- [律师操作手册](docs/lawyer_user_manual.md)
- [本地部署文档](docs/deployment_local_economical.md)
- [远程部署文档](docs/deployment_remote_economical.md)
- [远程维护与 CI/CD 运维档案](docs/remote_maintenance_runbook.md)

---

## 环境要求

| 工具 | 最低版本 | 说明 |
|------|---------|------|
| Docker | 24.0+ | 必须 |
| Docker Compose | 2.20+ | 必须 |
| Git | 2.x | 必须 |
| Node.js | 20.x | 前端开发时需要 |
| Python | 3.11+ | 后端本地开发时需要 |

---

## 快速启动（Docker，推荐）

### 第一步：克隆项目

```bash
git clone <your-repo-url>
cd imigrationAplication
```

### 第二步：配置环境变量

```bash
cp .env.example .env
```

用文本编辑器打开 `.env`，填入以下必要配置：

```env
# 必填：至少配置一个 LLM Provider
LLM_PROVIDER=minimax
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=xxxxxxxxxxxxxxxx

# 必填：修改为安全的密钥
SECRET_KEY=your-super-secret-key-at-least-32-chars
```

> 其余配置（数据库、Redis、MinIO）在 Docker 环境中已由 `docker-compose.yml` 自动配置，无需修改。

### 第三步：启动所有服务

```bash
docker compose up -d
```

首次启动会自动拉取镜像并构建，约需 3-5 分钟。

### 第四步：执行数据库迁移

```bash
docker compose exec api alembic upgrade head
```

这将创建所有数据库表并插入系统预设文件分类（奖项、专利、论文等）。

### 第五步：验证服务状态

```bash
docker compose ps
```

所有服务应显示 `running`：

```
NAME        STATUS
api         running   (port 8000)
worker      running
postgres    running   (port 5432)
redis       running   (port 6379)
minio       running   (port 9000, 9001)
frontend    running   (port 5173)
```

### 第六步：访问服务

| 服务 | 地址 | 说明 |
|------|------|------|
| **API 文档（Swagger）** | http://localhost:8000/api/docs | 交互式 API 文档 |
| **API 文档（Redoc）** | http://localhost:8000/api/redoc | 阅读友好版 |
| **前端界面** | http://localhost:5173 | React 应用 |
| **MinIO 控制台** | http://localhost:9001 | 文件存储管理（admin/minioadmin123） |
| **健康检查** | http://localhost:8000/health | 服务状态 |
| **就绪检查** | http://localhost:8000/health/ready | 数据库/Redis 状态 |

---

## 本地开发（不使用 Docker）

适合需要频繁调试后端代码的场景。

### 启动基础服务（PostgreSQL + Redis + MinIO）

```bash
# 只启动数据库相关服务，后端在本地运行
docker compose up -d postgres redis minio
```

### 后端本地运行

```bash
cd backend

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置本地环境变量（修改数据库地址为 localhost）
cp ../.env.example .env
# 将 .env 中的 DATABASE_URL 改为:
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/immigration_db
# REDIS_URL=redis://localhost:6379/0

# 执行数据库迁移
alembic upgrade head

# 可选：配置系统管理员邮箱，多个邮箱用英文逗号分隔。
# 匹配邮箱的用户注册或登录后会获得系统后台入口。
# SYSTEM_ADMIN_EMAILS=admin@example.com

# 启动 FastAPI（热重载模式）
uvicorn app.main:app --reload --port 8000
```

### 启动 Celery Worker（另一个终端）

```bash
cd backend
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

### 前端本地运行（另一个终端）

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

---

## 数据库操作

更多上线与远程维护流程见：[远程维护与 CI/CD 运维档案](docs/remote_maintenance_runbook.md)。

数据库结构以 Alembic 迁移为准：`backend/migrations/versions/*.py`。当前结构快照仅作阅读和归档参考，见 [docs/database/schema.sql](docs/database/schema.sql)。

### 配置第一个系统管理员

在后端环境变量中设置 `SYSTEM_ADMIN_EMAILS`，然后让该邮箱用户注册或重新登录：

```bash
SYSTEM_ADMIN_EMAILS=admin@example.com
```

管理员登录后可在侧边栏进入“系统后台”，管理用户启停和系统管理员权限。

### 查看当前迁移状态

```bash
docker compose exec api alembic current
```

### 回滚到上一版本

```bash
docker compose exec api alembic downgrade -1
```

### 创建新的迁移文件

```bash
docker compose exec api alembic revision --autogenerate -m "add new feature"
```

### 连接数据库（psql）

```bash
docker compose exec postgres psql -U postgres -d immigration_db
```

---

## 运行测试

```bash
# 后端全量测试
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v --tb=short

# 前端构建
cd ../frontend
npm ci
npm run build
```

上线前至少做一轮冒烟测试：管理员登录、创建案件、上传小文件并后台解析、在 Agent 运行记录查看解析结果、确认事实、选择少量事实生成文案、查看 Worker 日志无持续错误。

---

## 常用命令速查

```bash
# 查看所有服务日志
docker compose logs -f

# 只看 API 日志
docker compose logs -f api

# 只看 Celery Worker 日志
docker compose logs -f worker

# 就绪检查（数据库 + Redis）
curl http://localhost:8000/health/ready

# 重启 API 服务（修改代码后）
docker compose restart api

# 停止所有服务（保留数据）
docker compose stop

# 完全清除（包括数据库数据）⚠️ 慎用
docker compose down -v
```

线上排查提示：

- API 请求日志包含 `request_id`、路径、状态码和耗时。
- Agent Worker 日志包含任务开始、完成、失败和重试；失败原因会写入 `agent_tasks.error_message`。
- 文件解析、事实重解析、文案生成和 AI 重写都会写入案件内「Agent 运行记录」。记录中展示文件名、事实名、策略名、知识库标题等可读上下文，而不是只展示机器 ID。
- 系统会自动释放超过保护时间仍停留在 `queued/processing` 的 Agent 任务，释放后按钮可重新触发，旧 Worker 返回时不会覆盖新结果。
- Redis 用于队列、列表缓存和 LLM 短 TTL 缓存；Redis 异常时页面缓存会降级，但 Celery 队列会受影响。
- 文档、事实、任务、文案、案件和会话接口会按案件成员校验权限，避免跨案件读写。

---

## 部署方案

当前推荐用 Docker Compose 做最直接、最经济的部署：

- 远程部署：单台 VPS 或便宜托管云服务组合，见 [远程部署方案](docs/deployment_remote_economical.md)。
- 本地部署：办公室电脑/内网服务器 + Docker Compose，并配置大模型调用，见 [本地部署方案](docs/deployment_local_economical.md)。
- 律师使用说明：见 [律师操作手册](docs/lawyer_user_manual.md)。

生产远程部署使用 `docker-compose.prod.yml` 和 `deploy/Caddyfile.prod`；开发和本机快速试用继续使用 `docker-compose.yml`。

---

## 目录结构

```
imigrationAplication/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── main.py             # 应用入口
│   │   ├── config.py           # 环境配置
│   │   ├── models/             # 数据库模型（13张表）
│   │   ├── routers/            # API 路由（9个模块）
│   │   ├── middleware/         # JWT 认证、多租户、i18n
│   │   ├── agents/             # AI Agent 模块
│   │   ├── llm/                # LLM 多模型抽象层
│   │   └── workers/            # Celery 异步任务
│   ├── migrations/             # Alembic 数据库迁移
│   ├── tests/                  # 测试文件
│   ├── requirements.txt         # 运行时依赖
│   └── requirements-dev.txt     # 本地测试依赖
├── frontend/                   # React 前端
├── docs/                       # 需求、实现、部署、运维、数据库快照和用户手册
├── deploy/                     # 生产反向代理配置
├── docker-compose.yml          # 本地开发环境
├── docker-compose.prod.yml     # 单机生产部署
├── .env.example                # 环境变量模板
├── .github/workflows/ci.yml    # CI/CD 流水线
└── README.md                   # 本文档
```

---

## 常见问题

**Q: `docker compose up` 报端口冲突？**
```bash
# 检查占用端口的进程
lsof -i :5432   # PostgreSQL
lsof -i :6379   # Redis
lsof -i :8000   # API
# 修改 docker-compose.yml 中对应的端口映射
```

**Q: 数据库迁移报错 `relation already exists`？**
```bash
# 标记当前状态为最新，跳过已存在的表
docker compose exec api alembic stamp head
```

**Q: LLM 调用失败？**
- 确认 `.env` 中已填入有效的 API Key
- 检查网络是否能访问对应的 LLM 服务
- 如需本地大模型，将 `.env` 设置为 `LLM_PROVIDER=ollama`、`LLM_MODEL=llama3.1:8b`、`LLM_BASE_URL=http://host.docker.internal:11434/v1`，并确保 Ollama 已启动且模型已下载

**Q: MinIO 文件上传失败？**
```bash
# 手动创建存储桶
docker compose exec minio mc alias set local http://localhost:9000 minioadmin minioadmin123
docker compose exec minio mc mb local/immigration-docs
```

---

## 联系与支持

- **产品需求文档**：见 [docs/product_requirements.md](docs/product_requirements.md)
- **技术实现文档**：见 [docs/implementation.md](docs/implementation.md)
- **API 文档**：http://localhost:8000/api/docs（启动后访问）
