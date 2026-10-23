# 远程部署文档：经济型上线方案

[English guide](implementation.en.md#production-operations) · [命名兼容与备份说明](naming-and-backup.md)

更新时间：2026-10-23
目标：把当前系统稳定放到公网访问，并能远程 CI/CD、备份、排障和回滚。

详细运维 Runbook 见：`docs/remote_maintenance_runbook.md`。

## 1. 当前推荐方案

首选方案：单台 VPS + Docker Compose。

| 服务 | 当前实现 |
|------|----------|
| 入口/HTTPS | Caddy |
| 前端 | `frontend/dist` 静态文件 |
| API | FastAPI |
| 异步任务 | Celery Worker |
| 数据库 | PostgreSQL |
| 缓存/队列 | Redis |
| 文件存储 | MinIO，或替换为 R2/Supabase Storage |
| 大模型 | MiniMax / OpenAI-compatible / Claude / Gemini / Ollama |

为什么先选单台 VPS：

- 当前项目不是纯 Serverless。审计底稿生成、AI 重写等依赖常驻 Worker 和 Redis。
- 单机 Compose 最容易保证 API、Worker、DB、Redis、存储之间网络稳定。
- 成本固定，早期排障简单。

后续可升级：

- 前端放 Vercel/Cloudflare Pages。
- Postgres/Redis/对象存储迁到托管服务。
- API/Worker 放 Railway/Fly.io/Render。
- CI 构建镜像推送 GHCR，服务器只拉镜像。

## 2. 服务器配置

建议：

| 场景 | 配置 |
|------|------|
| MVP/小团队 | 2 vCPU / 4 GB RAM / 60 GB SSD |
| 更稳 | 4 vCPU / 8 GB RAM / 100 GB SSD |
| 扫描件多、任务多 | 4-8 vCPU / 8-16 GB RAM |

系统：

- Ubuntu 22.04 LTS 或 24.04 LTS。
- Docker 24+。
- Docker Compose plugin 2.20+。

安装：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw fail2ban
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

重新登录后：

```bash
docker version
docker compose version
```

## 3. DNS 和防火墙

DNS：

```text
app.yourdomain.com -> VPS 公网 IP
```

防火墙：

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

不要暴露：

- PostgreSQL
- Redis
- MinIO API
- MinIO Console

MinIO 控制台只通过 SSH tunnel：

```bash
ssh -L 9001:127.0.0.1:9001 user@app.yourdomain.com
```

然后访问：

```text
http://localhost:9001
```

## 4. 部署目录

推荐：

```bash
sudo mkdir -p /opt/immigration-app
sudo chown -R $USER:$USER /opt/immigration-app
cd /opt/immigration-app
git clone <your-repo-url> .
cp .env.example .env
```

## 5. 生产 `.env`

至少修改：

```env
APP_DOMAIN=app.yourdomain.com
DEBUG=false
SECRET_KEY=请改成至少32位随机字符串

POSTGRES_DB=immigration_db
POSTGRES_PASSWORD=请改成强密码

CORS_ORIGINS=["https://app.yourdomain.com"]

STORAGE_ACCESS_KEY=请改成强用户名
STORAGE_SECRET_KEY=请改成强密码
STORAGE_BUCKET_NAME=immigration-docs

SYSTEM_ADMIN_EMAILS=admin@example.com

LLM_PROVIDER=minimax
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=你的模型APIKey
LLM_TIMEOUT_SECONDS=120

CACHE_ENABLED=true
CACHE_TTL_SECONDS=45
ADMIN_CACHE_TTL_SECONDS=15

AGENT_TASK_QUEUED_TIMEOUT_MINUTES=10
AGENT_TASK_PROCESSING_TIMEOUT_MINUTES=18
DRAFT_TASK_SOFT_TIME_LIMIT_SECONDS=420
DRAFT_TASK_TIME_LIMIT_SECONDS=480
PARSE_TASK_SOFT_TIME_LIMIT_SECONDS=900
PARSE_TASK_TIME_LIMIT_SECONDS=960
```

说明：

- `SYSTEM_ADMIN_EMAILS` 用于配置第一个系统管理员。
- API 和 Worker 必须使用同一组 LLM、Redis、数据库、对象存储变量。
- 修改 `.env` 后需要重新创建 `api` 和 `worker`。
- `DEBUG` 必须使用布尔值，例如 `false`，不要写成 `release` 等环境名。
- Agent 超时变量用于释放卡住的排队/处理中任务，线上建议先使用本文默认值，再根据真实模型速度微调。

## 6. 首次上线

```bash
cd /opt/immigration-app

cd frontend
npm ci
npm run build
cd ..

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml ps
```

检查：

```bash
curl -fsS https://app.yourdomain.com/health/ready
docker compose -f docker-compose.prod.yml exec api alembic current
docker compose -f docker-compose.prod.yml logs --tail=100 api
docker compose -f docker-compose.prod.yml logs --tail=100 worker
```

`alembic current` 应显示最新 head，例如：

```text
013_database_cache_indexes (head)
```

## 7. CI/CD

当前仓库已有 `.github/workflows/ci.yml`：

- 后端：PostgreSQL + Redis，安装 `requirements-dev.txt`，执行迁移和测试。
- 前端：`npm ci && npm run build`。
- main 分支可接部署 job。

GitHub Secrets 建议：

| Secret | 用途 |
|--------|------|
| `PROD_HOST` | 服务器 IP 或域名 |
| `PROD_USER` | 部署用户 |
| `PROD_SSH_KEY` | 部署私钥 |
| `PROD_PORT` | SSH 端口 |
| `APP_DOMAIN` | 线上域名 |

生产业务密钥不要放进 workflow，放服务器 `/opt/immigration-app/.env`。

最小远程发布脚本：

```bash
set -euo pipefail

APP_DIR=/opt/immigration-app
COMPOSE="docker compose -f docker-compose.prod.yml"

cd "$APP_DIR"
git fetch --prune
git checkout main
git pull --ff-only

cd frontend
npm ci
npm run build
cd ..

$COMPOSE build api worker
$COMPOSE up -d postgres redis minio
$COMPOSE run --rm api alembic upgrade head
$COMPOSE up -d --remove-orphans

curl -fsS "https://${APP_DOMAIN}/health/ready"
docker image prune -f
```

更详细流程见 `docs/remote_maintenance_runbook.md`。

## 8. Agent 线上稳定性配置

线上最容易卡住的不是页面，而是大模型请求、OCR、Redis 队列或 Worker 没启动。

必须确认：

- `api` 服务运行。
- `worker` 服务运行。
- `redis` 正常。
- `/health/ready` 返回 `db=ok`、`redis=ok`。
- LLM Provider 的 API Key、Base URL、Model 都正确。
- 模型设置页「测试生成」通过。

推荐环境变量：

```env
LLM_TIMEOUT_SECONDS=120
LLM_CACHE_ENABLED=true
LLM_CACHE_TTL_SECONDS=900

AGENT_TASK_QUEUED_TIMEOUT_MINUTES=10
AGENT_TASK_PROCESSING_TIMEOUT_MINUTES=18

PARSE_MAX_CONTENT_CHARS=8500
PARSE_MAX_FACTS=18
PARSE_MAX_OUTPUT_TOKENS=1800
PARSE_TASK_SOFT_TIME_LIMIT_SECONDS=900
PARSE_TASK_TIME_LIMIT_SECONDS=960

DRAFT_MAX_FACTS=24
DRAFT_MAX_KNOWLEDGE_ITEMS=4
DRAFT_GENERATION_MAX_TOKENS=2400
DRAFT_REWRITE_MAX_TOKENS=1800
DRAFT_TASK_SOFT_TIME_LIMIT_SECONDS=420
DRAFT_TASK_TIME_LIMIT_SECONDS=480
```

当前保护策略：

- 文件解析、事实重解析、审计底稿生成和 AI 重写都会写入审计项目内「Agent 运行记录」。
- 同一文件解析中、同一事实重解析中、同一审计项目审计底稿生成中会阻止重复触发。
- 超过保护时间仍停留在 `queued/processing` 的任务会自动标记失败并释放按钮。
- 旧 Worker 如果晚返回，会先检查任务状态，不会覆盖已经释放或重新发起后的结果。

如果线上模型经常超时：

- 优先减少审计人员单次选择的事实数量。
- 知识库只选最相关 1-4 条。
- 把“生成整封审计报告”拆成“生成某个论证段落”。
- 文件解析先用较小文件测试。
- Worker 并发不要盲目调高，小 VPS 建议 `--concurrency=2`。
- 查看审计项目内「Agent 运行记录」、`agent_tasks.error_message` 和 worker 日志。

## 9. 日常维护

查看服务：

```bash
docker compose -f docker-compose.prod.yml ps
```

查看日志：

```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f worker
```

重启：

```bash
docker compose -f docker-compose.prod.yml restart api worker
```

迁移：

```bash
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml exec api alembic current
```

健康检查：

```bash
curl -fsS https://app.yourdomain.com/health/ready
```

Redis 队列：

```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
docker compose -f docker-compose.prod.yml exec redis redis-cli -n 1 llen celery
```

## 10. 备份

数据库：

```bash
mkdir -p backups/db
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U postgres immigration_db > backups/db/immigration_$(date +%F_%H%M).sql
```

MinIO：

```bash
mkdir -p backups/minio
docker run --rm \
  -v imigrationaplication_minio_data:/data:ro \
  -v "$PWD/backups/minio:/backup" \
  alpine tar czf /backup/minio_$(date +%F_%H%M).tgz /data
```

建议：

- 每天备份。
- 每周做一次恢复演练。
- 备份同步到服务器外部，例如 NAS、R2、B2、S3。
- 备份文件加密保存。

## 11. 回滚

优先回滚代码，不轻易回滚数据库：

```bash
cd /opt/immigration-app
git fetch --tags
git checkout <previous-good-commit>

cd frontend
npm ci
npm run build
cd ..

docker compose -f docker-compose.prod.yml up -d --build api worker caddy
curl -fsS https://${APP_DOMAIN}/health/ready
```

数据库 downgrade 只有在 migration 明确支持且测试过时才执行：

```bash
docker compose -f docker-compose.prod.yml exec api alembic downgrade -1
```

## 12. 可选托管组合

如果不想自管数据层，可以逐步替换：

| 模块 | 可选服务 |
|------|----------|
| 前端 | Vercel / Cloudflare Pages |
| API/Worker | Railway / Fly.io / Render |
| PostgreSQL | Supabase / Neon / RDS |
| Redis | Upstash / Redis Cloud |
| 对象存储 | Cloudflare R2 / Supabase Storage / S3 |

注意：

- API 和 Worker 必须都部署。
- API 与 Worker 必须使用同一个数据库、Redis 和对象存储。
- 托管 Redis 如果只支持一个逻辑库，就让 `REDIS_URL`、`CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND` 使用同一条连接串。
- 使用托管 PostgreSQL 时要同时配置 `DATABASE_URL` 和 `DATABASE_URL_SYNC`。

## 13. 上线检查清单

发布前：

- 后端测试通过。
- 前端构建通过。
- migration 已在测试库跑过。
- `.env` 生产变量已检查。
- 数据库和上传文件已备份。
- 系统管理员邮箱已配置。

发布后：

- `/health/ready` 正常。
- API 和 Worker 都在运行。
- 管理员能登录系统后台。
- 模型设置页测试生成成功。
- 上传小文件并触发后台解析成功。
- 在审计项目内「Agent 运行记录」能看到文件解析记录、诊断信息和提取事实数。
- 选择少量事实生成报告成功。
- 审计底稿生成和 AI 重写记录能展示可读的事实依据、策略名和知识库标题。
- Worker 日志无持续错误。
