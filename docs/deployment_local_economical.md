# 本地部署文档：办公室电脑/内网服务器

[English guide](../README.en.md#local-development) · [命名兼容与备份说明](naming_and_backup.md)

更新时间：2026-10-23
目标：用 Docker Compose 在本机或内网服务器运行整套系统，让数据库、文件、缓存和队列留在本地。

## 1. 适用场景

适合：

- 个人审计人员或 2-3 人试用。
- 审计机构内网演示和长期试运行。
- 希望审计项目材料默认留在本机或内网。
- 需要先验证 Agent 解析和审计底稿生成流程，再决定是否远程上线。

不适合：

- 需要公网稳定访问但没有运维人员。
- 需要多人跨地域访问且无 VPN/内网穿透。
- 希望完全免维护数据库、Redis、对象存储。

## 2. 推荐配置

| 场景 | 建议配置 |
|------|----------|
| 轻量试用 | 4 核 CPU / 8 GB RAM / 100 GB SSD |
| 稳定多人试用 | 8 核 CPU / 16 GB RAM / 500 GB SSD |
| 大量扫描件 OCR | 8 核 CPU / 16 GB RAM 起步 |
| 本地大模型 | 32 GB RAM 起步；建议独立显卡 |

本地 Docker 启动：

- PostgreSQL
- Redis
- MinIO
- FastAPI API
- Celery Worker
- React/Vite 前端

## 3. 快速启动

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api alembic upgrade head
```

访问：

```text
前端：http://localhost:5173
API 文档：http://localhost:8000/api/docs
MinIO 控制台：http://localhost:9001
健康检查：http://localhost:8000/health/ready
```

检查：

```bash
docker compose ps
curl http://localhost:8000/health/ready
```

`/health/ready` 应显示：

```json
{"checks":{"db":"ok","redis":"ok"}}
```

## 4. 必填环境变量

本地 `.env` 至少检查：

```env
DEBUG=false
SECRET_KEY=请改成至少32位随机字符串

DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/immigration_db
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

STORAGE_ENDPOINT_URL=http://minio:9000
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=请改成强密码
STORAGE_BUCKET_NAME=immigration-docs

SYSTEM_ADMIN_EMAILS=admin@example.com

AGENT_TASK_QUEUED_TIMEOUT_MINUTES=10
AGENT_TASK_PROCESSING_TIMEOUT_MINUTES=18
DRAFT_TASK_SOFT_TIME_LIMIT_SECONDS=420
DRAFT_TASK_TIME_LIMIT_SECONDS=480
PARSE_TASK_SOFT_TIME_LIMIT_SECONDS=900
PARSE_TASK_TIME_LIMIT_SECONDS=960
```

第一个管理员：

1. 设置 `SYSTEM_ADMIN_EMAILS=你的邮箱`。
2. 重启 API。
3. 用该邮箱注册或重新登录。
4. 侧边栏出现「系统后台」。

```bash
docker compose up -d --force-recreate --no-deps api worker
```

## 5. 大模型配置

不配置大模型时，登录、审计项目、上传、任务、知识库等基础功能可用；以下功能不可用或会失败：

- AI 解析文件
- 事实异议重新解析
- 审计底稿生成
- AI 重写
- 翻译
- 模型测试生成

### 外部模型 API

推荐先使用稳定的 OpenAI-compatible 网关或 MiniMax：

```env
LLM_PROVIDER=minimax
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=你的模型APIKey
LLM_TIMEOUT_SECONDS=120
```

也可以使用兼容 `/v1` 的网关：

```env
LLM_PROVIDER=openai
LLM_MODEL=your-model
LLM_BASE_URL=https://your-gateway.example/v1
LLM_API_KEY=你的APIKey
```

修改 `.env` 后重启：

```bash
docker compose up -d --force-recreate --no-deps api worker
```

### 本地 Ollama

适合严格内网环境，但速度和质量取决于硬件。

```bash
ollama pull llama3.1:8b
ollama serve
```

`.env`：

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=
```

Linux 容器访问不了 `host.docker.internal` 时，改为宿主机内网 IP：

```env
LLM_BASE_URL=http://192.168.1.20:11434/v1
```

## 6. Agent 不易卡住的本地使用建议

文件解析：

- 优先上传可复制文本的 PDF、Word、TXT。
- 大扫描件建议先拆成较小文件，或先做 OCR。
- 一次解析一个文件，不要连续点多个大文件。
- 文件类型要选准，例如合同与协议、内部控制、函证与声明。
- 解析提示词只写本文件要提取的重点，不要粘贴整套法律模板。
- 知识库参考只选 1-3 条最相关的提示词模板或 Agent 策略。

审计底稿生成：

- 先在事实库确认事实，再生成报告。
- 每次选择 6-15 条最相关事实，避免全选所有事实。
- 一次只生成一个明确段落或主题，例如 `original contributions`、`proposed endeavor`。
- 知识库最多选 1-4 条，优先选结构模板和 Agent 策略。
- 不要重复点击生成。系统已防重复任务，重复点击只会增加等待和误解。
- 文件解析、事实重解析、审计底稿生成和 AI 重写都会进入审计项目内「Agent 运行记录」。本地试运行时重点看这里的诊断、错误和耗时。
- 如果任务超过保护时间仍未完成，系统会自动标记失败并释放按钮；释放后缩小文件、事实或知识库范围再试。

重写和翻译：

- 重写指令要短而具体，例如“保留事实，改成更正式、客观的审计报告语气”。
- 翻译长报告时按段落处理，减少远端超时。

## 7. 内网多人访问

查看服务器内网 IP：

```bash
ip addr
```

假设服务器 IP 为 `192.168.1.20`：

```text
前端：http://192.168.1.20:5173
API：http://192.168.1.20:8000/api/docs
```

`.env`：

```env
CORS_ORIGINS=["http://192.168.1.20:5173","http://localhost:5173"]
```

重启：

```bash
docker compose restart api frontend
```

## 8. 本地生产化运行

如果希望只用一个入口访问：

```bash
cd frontend
npm ci
npm run build
cd ..

APP_DOMAIN=localhost docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

访问：

```text
http://localhost
```

长期内网使用建议：

```env
APP_DOMAIN=immigration.local
CORS_ORIGINS=["http://immigration.local","http://192.168.1.20"]
```

## 9. 常用维护命令

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker
docker compose restart api worker
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

升级代码：

```bash
git pull
docker compose up -d --build
docker compose exec api alembic upgrade head
```

说明：

- Redis 用于 Celery 队列、页面缓存和 LLM 缓存。
- API 日志包含路径、状态码、耗时和 `request_id`。
- Worker 日志包含审计底稿生成、重写、RFI 等任务状态。

## 10. 备份与恢复

数据库备份：

```bash
mkdir -p backups
docker compose exec -T postgres \
  pg_dump -U postgres immigration_db > backups/immigration_$(date +%F).sql
```

MinIO 文件备份：

```bash
docker run --rm \
  -v imigrationaplication_minio_data:/data:ro \
  -v "$PWD/backups:/backup" \
  alpine tar czf /backup/minio_$(date +%F).tgz /data
```

恢复数据库：

```bash
docker compose exec -T postgres \
  psql -U postgres -d immigration_db < backups/immigration_YYYY-MM-DD.sql
```

备份建议：

- 每天至少备份数据库。
- 上传文件 volume 也要备份。
- 备份应复制到审计机构 NAS、加密移动硬盘或云端加密桶。

## 11. 安全检查

- 不要把 PostgreSQL、Redis、MinIO、Ollama 直接暴露公网。
- 修改 `SECRET_KEY`、数据库密码、MinIO 密码。
- 重要材料建议加密备份。
- 使用外部大模型前，确认审计机构允许把提示词、事实和报告上下文发送给 Provider。
- 如果必须避免模型调用出网，使用 Ollama 或内网模型网关。
- 系统管理员邮箱变更后，应及时更新 `SYSTEM_ADMIN_EMAILS`。

## 12. 推荐结论

- 个人试用：`docker compose up -d --build`
- 审计机构内网试运行：Ubuntu 小主机 + Docker Compose + 外部稳定模型 API
- 对数据出网敏感：Docker Compose + VPN + Ollama/内网模型网关
- 要公网稳定访问：参考 `docs/deployment_remote_economical.md`
