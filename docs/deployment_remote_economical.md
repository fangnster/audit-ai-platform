# 远程部署方案：便宜云服务优先

目标：最直接、经济地把系统放到公网访问。适合 1 个律所、小团队试运行或 MVP。

## 方案选择

有两种可选方案：

| 方案 | 适合 | 优点 | 代价 |
|------|------|------|------|
| A. 单台 VPS + Docker Compose | 想最快上线、少折腾、成本固定 | 一个服务器跑完全部组件，部署简单 | 数据库、Redis、存储都要自己备份 |
| B. 便宜托管云服务组合 | 希望减少数据库/存储维护 | 前端、数据库、对象存储可用低价/免费层 | 配置更多，Worker/API 仍需部署平台 |

## 方案 A：单台 VPS + Docker Compose

使用一台云服务器运行所有服务：

- Caddy：HTTPS、反向代理、前端静态文件
- FastAPI：后端 API
- Celery Worker：Agent 异步任务
- PostgreSQL + pgvector：数据库
- Redis：队列和缓存
- MinIO：对象存储
- 外部 LLM API：MiniMax / OpenAI Compatible / Claude / Gemini / Ollama 网关

推荐服务器：

- 最低：2 vCPU / 4 GB RAM / 60 GB SSD
- 更稳：4 vCPU / 8 GB RAM / 100 GB SSD
- 系统：Ubuntu 22.04 LTS 或 24.04 LTS

成本：

- VPS：约 5-12 美元/月起
- 域名：约 10-15 美元/年
- LLM：按调用量付费
- 不额外购买托管数据库、托管 Redis 或对象存储，先把成本压到最低

### 1. 准备服务器

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw
```

安装 Docker 和 Docker Compose plugin：

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

重新登录服务器后验证：

```bash
docker version
docker compose version
```

### 2. 配置 DNS

把域名 A 记录指向服务器公网 IP：

```text
app.yourdomain.com -> 服务器公网 IP
```

Caddy 会自动申请和续期 HTTPS 证书。

### 3. 拉取代码并配置环境变量

```bash
git clone <your-repo-url>
cd imigrationAplication
cp .env.example .env
```

生产环境 `.env` 至少修改：

```env
APP_DOMAIN=app.yourdomain.com
DEBUG=false
SECRET_KEY=请改成至少32位随机字符串
POSTGRES_PASSWORD=请改成强密码
POSTGRES_DB=immigration_db

CORS_ORIGINS=["https://app.yourdomain.com"]

STORAGE_ACCESS_KEY=请改成强用户名
STORAGE_SECRET_KEY=请改成强密码
STORAGE_BUCKET_NAME=immigration-docs

LLM_PROVIDER=minimax
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=你的模型APIKey
```

### 4. 构建前端并启动服务

```bash
cd frontend
npm ci
npm run build
cd ..

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml ps
```

访问：

```text
https://app.yourdomain.com
https://app.yourdomain.com/api/docs
```

### 5. 防火墙

只开放 SSH、HTTP、HTTPS：

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

PostgreSQL、Redis、MinIO API 不暴露公网。MinIO 控制台只绑定到服务器本机 `127.0.0.1:9001`，需要维护时用 SSH 端口转发：

```bash
ssh -L 9001:127.0.0.1:9001 user@app.yourdomain.com
```

然后打开 `http://localhost:9001`。

### 6. 日常维护

查看日志：

```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f worker
```

健康检查：

```bash
curl http://127.0.0.1/health
curl http://127.0.0.1/health/ready
```

运维关注点：

- API 日志会输出 `request_id`、请求路径、状态码和耗时；线上排查时先用 `request_id` 串联 API 与前端问题。
- Worker 日志会输出 Agent 任务开始、完成、失败和重试；失败任务同时会写入 `agent_tasks.error_message`。
- Redis 同时用于 Celery、短 TTL 页面列表缓存和 LLM 结果缓存；如果 Redis 异常，系统会降级为数据库直查，但队列任务会受影响。
- 关键列表缓存默认 TTL 较短，写操作和 Agent 完成后会按案件维度主动失效，避免律师看到长时间旧数据。
- 文档、事实、任务、文案、案件和会话接口按案件成员校验权限；上线前应保留这一类鉴权回归测试。
- 每次发布后都运行 `alembic upgrade head`，新增索引用于文档、事实、文案、任务等排序和筛选。

更新代码：

```bash
git pull
cd frontend && npm ci && npm run build && cd ..
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

备份数据库：

```bash
mkdir -p backups
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U postgres immigration_db > backups/immigration_$(date +%F).sql
```

备份上传文件：

```bash
docker run --rm \
  -v imigrationaplication_minio_data:/data:ro \
  -v "$PWD/backups:/backup" \
  alpine tar czf /backup/minio_$(date +%F).tgz /data
```

## 方案 B：便宜托管云服务组合

如果你愿意多配置几个服务，可以把最容易出问题的数据层交给便宜云服务，应用层保持 Docker 部署。

推荐组合：

| 模块 | 推荐便宜服务 | 用途 |
|------|--------------|------|
| 前端 | Cloudflare Pages | 托管 `frontend/dist` 静态文件 |
| API/Worker | Fly.io / Render / Railway 任选其一 | 跑 FastAPI 和 Celery Worker |
| PostgreSQL | Neon / Supabase | 托管 PostgreSQL，省掉数据库运维 |
| Redis | Upstash Redis | Celery Broker/Result Backend |
| 对象存储 | Cloudflare R2 | S3-compatible 文档存储 |
| LLM | MiniMax / OpenAI-compatible / Claude / Gemini | 按量调用 |

## 方案 B-2：Vercel + Railway + Supabase + Upstash 具体步骤

你选择的 `Vercel + Railway + Supabase + Upstash` 是当前项目最合适的低成本托管组合之一。当前项目不是纯 Serverless 架构：后端是 FastAPI，异步解析/生成依赖 Celery Worker 和 Redis。最稳妥的上线方式是：

- Vercel：部署 React 前端。
- Railway：部署 FastAPI API 和 Celery Worker。
- Supabase：托管 Postgres 和 Storage。
- Upstash Redis：托管 Redis，供 Celery 队列和缓存使用。

也就是说，先做到“数据层托管 + 前端托管”，后端暂时不改架构。后续如果一定要纯 Vercel Serverless，需要把 FastAPI 路由、Celery 队列、文件解析 Worker 重构为 Vercel Functions / Supabase Edge Functions / 队列任务，这不是点击部署级别的改动。

当前官方免费/低价额度要按最新口径理解：

| 服务 | 平台 | 当前免费/低价口径 | 本项目用法 |
|------|------|------------------|------------|
| 前端 | Vercel Hobby | 100 GB/月 Fast Data Transfer | 连接 GitHub 自动部署 `frontend` |
| 后端 API | Railway | 新用户 30 天 $5 trial；之后 Free 每月 $1 credit，Hobby $5/月含 $5 usage | 一个 Railway Service 跑 FastAPI |
| Worker | Railway | 同上，和 API 分开计资源 | 第二个 Railway Service 跑 Celery Worker |
| 数据库 | Supabase Free | 500 MB database size；1 GB disk；2 个 free projects | Postgres |
| 文件存储 | Supabase Storage Free | 1 GB Storage | 上传文件 bucket |
| Redis | Upstash Redis Free | 256 MB；500K commands/month；1 个 free database | Celery broker/result + cache |

注意：Railway 不是“500 小时/月”固定免费口径了。API + Worker 是两个常驻进程，Free/Trial 更适合试部署；如果要 24 小时稳定跑，通常按 Railway Hobby 或小 VPS 预算更现实。

### 1. 创建 Supabase 项目

1. 在 Supabase 新建项目，区域选择离 API/用户最近的区域。
2. 进入 `Project Settings -> Database`，复制连接串。
3. 当前 API 是长期运行的容器服务，优先使用 `Session pooler` 或 `Direct connection`；如果以后把 API 改成真正 Serverless，再用 `Transaction pooler`。
4. 准备两条数据库连接：

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/postgres?ssl=require
DATABASE_URL_SYNC=postgresql+psycopg2://USER:PASSWORD@HOST:PORT/postgres?sslmode=require
```

`DATABASE_URL` 给 FastAPI 运行时使用；`DATABASE_URL_SYNC` 给 Alembic 迁移使用。

### 2. 创建 Supabase Storage Bucket

1. 进入 `Storage`，创建 bucket，例如：

```text
immigration-docs
```

2. 建议先设为 private。文件下载走后端鉴权，不需要把 bucket 公开。
3. 进入 Supabase Storage 的 S3 设置，创建 S3 access key。
4. 配置后端环境变量：

```env
STORAGE_ENDPOINT_URL=https://<project-ref>.storage.supabase.co/storage/v1/s3
STORAGE_ACCESS_KEY=<supabase-storage-s3-access-key>
STORAGE_SECRET_KEY=<supabase-storage-s3-secret-key>
STORAGE_BUCKET_NAME=immigration-docs
STORAGE_REGION=<supabase-project-region>
STORAGE_PUBLIC_URL=
```

### 3. 创建 Redis

用 Upstash Redis 创建一个数据库，复制 `rediss://...` 连接串：

```env
REDIS_URL=rediss://default:PASSWORD@HOST:PORT
CELERY_BROKER_URL=rediss://default:PASSWORD@HOST:PORT
CELERY_RESULT_BACKEND=rediss://default:PASSWORD@HOST:PORT
CACHE_ENABLED=true
```

不要手动把 Upstash 地址改成 `/1`、`/2`。Upstash 免费库通常只有一个逻辑库，项目代码会在 Celery 使用 `rediss://` 时自动补齐 SSL 参数。

### 4. 部署 API 和 Worker 到 Railway

在 Railway 新建一个 Project，然后从同一个 GitHub 仓库创建两个 Service。

第一个 Service：`api`

```text
Source: GitHub repo
Root Directory: 留空
Builder: Dockerfile
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

第二个 Service：`worker`

```text
Source: 同一个 GitHub repo
Root Directory: 留空
Builder: Dockerfile
Start Command: celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
```

本地等价命令是：

```bash
# API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Worker
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
```

API 和 Worker 必须使用同一组环境变量。Railway 里建议先建 Shared Variables，两个 Service 都引用：

```env
DEBUG=false
SECRET_KEY=请改成至少32位随机字符串
APP_TIMEZONE=Asia/Shanghai
CORS_ORIGINS=["https://你的-vercel-域名.vercel.app","https://app.yourdomain.com"]

DATABASE_URL=...
DATABASE_URL_SYNC=...

REDIS_URL=...
CELERY_BROKER_URL=...
CELERY_RESULT_BACKEND=...

STORAGE_ENDPOINT_URL=...
STORAGE_ACCESS_KEY=...
STORAGE_SECRET_KEY=...
STORAGE_BUCKET_NAME=immigration-docs
STORAGE_REGION=...

LLM_PROVIDER=openai
LLM_MODEL=你的模型名称
LLM_BASE_URL=你的 OpenAI-compatible /v1 地址
LLM_API_KEY=你的新 API Key
```

部署后先跑数据库迁移。最简单的方式是在 Railway 的 API Service 打开 Shell/Run Command 执行：

```bash
alembic upgrade head
```

再检查：

```bash
curl https://api.yourdomain.com/health
curl https://api.yourdomain.com/health/ready
```

### 5. 部署前端到 Vercel

在 Vercel 导入 Git 仓库，项目设置：

```text
Framework Preset: Vite
Root Directory: frontend
Build Command: npm run build
Output Directory: dist
Install Command: npm ci
```

在 Vercel 环境变量里设置：

```env
VITE_API_BASE_URL=https://api.yourdomain.com/api/v1
```

如果暂时没有独立 API 域名，也可以填容器平台给你的 API 地址，例如：

```env
VITE_API_BASE_URL=https://your-api.up.railway.app/api/v1
```

前端已包含 `frontend/vercel.json`，用于让 React Router 的深链接刷新时回到 `index.html`，避免 `/cases/...` 这类页面在 Vercel 上刷新 404。

### 6. 绑定域名

推荐：

```text
app.yourdomain.com -> Vercel 前端
api.yourdomain.com -> API 容器服务
```

然后把 API 的 `CORS_ORIGINS` 改成：

```env
CORS_ORIGINS=["https://app.yourdomain.com"]
```

### 7. 上线前检查清单

1. Supabase 数据库能连通，`alembic upgrade head` 成功。
2. API `/health` 和 `/health/ready` 正常。
3. Vercel 前端登录、注册、建案正常。
4. 上传文件后，Supabase Storage bucket 里能看到对象。
5. 手动触发解析，Worker 日志能看到任务执行。
6. 设置页保存模型配置后，“测试生成”成功。
7. 文案生成和重写能正常入队，并最终生成内容。
8. 不要把真实 `.env` 或 API Key 提交到 Git。已经暴露过的 Key 建议立即轮换。

最省事的落地方式：

1. 前端构建后部署到 Cloudflare Pages。
2. API 和 Worker 各作为一个服务部署到同一家应用平台，使用同一份环境变量。
3. 数据库使用 Neon/Supabase 连接串，写入 `DATABASE_URL`。
4. Redis 使用 Upstash 连接串，写入 `REDIS_URL`、`CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND`。
5. R2 创建 bucket，写入 `STORAGE_ENDPOINT_URL`、`STORAGE_ACCESS_KEY`、`STORAGE_SECRET_KEY`、`STORAGE_BUCKET_NAME`。
6. 部署后运行 `alembic upgrade head`。

便宜云服务 `.env` 示例：

```env
DEBUG=false
SECRET_KEY=请改成至少32位随机字符串
CORS_ORIGINS=["https://app.yourdomain.com"]

DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DB?ssl=require

REDIS_URL=rediss://default:PASSWORD@HOST:PORT
CELERY_BROKER_URL=rediss://default:PASSWORD@HOST:PORT
CELERY_RESULT_BACKEND=rediss://default:PASSWORD@HOST:PORT

STORAGE_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
STORAGE_ACCESS_KEY=R2_ACCESS_KEY
STORAGE_SECRET_KEY=R2_SECRET_KEY
STORAGE_BUCKET_NAME=immigration-docs

LLM_PROVIDER=minimax
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=你的模型APIKey
```

注意：

- 远程托管方案必须确认 API 服务和 Worker 都能访问同一个数据库、Redis 和对象存储。
- Celery 对 Redis URL 支持度与平台有关；如果 Upstash 的 Redis 连接出现兼容问题，优先把 API/Worker/Redis 放回单台 VPS。
- 免费层/低价层限制经常变化，采购前以各服务商官方价格页为准。

## 什么时候升级架构

以下情况再考虑托管数据库或拆分服务：

- 并发律师明显增加，单机 CPU/RAM 长期吃满
- 上传文件超过单机磁盘容量
- 需要跨地区访问和高可用
- 需要严格的自动备份、审计和灾备 SLA

## 参考

- Docker Compose Linux 安装：https://docs.docker.com/compose/install/linux/
- Caddy 自动 HTTPS：https://caddyserver.com/docs/automatic-https
- Cloudflare R2 S3 兼容 API：https://developers.cloudflare.com/r2/api/s3/api/
- Cloudflare Pages 定价：https://www.cloudflare.com/developer-platform/products/pages/
- Neon 定价：https://neon.com/pricing
- Upstash Redis 定价：https://upstash.com/pricing/redis
