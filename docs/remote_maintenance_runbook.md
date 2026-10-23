# 远程维护与 CI/CD 运维档案

[English guide](implementation.en.md#production-operations) · [命名兼容与备份说明](naming_and_backup.md)

目标：把当前项目从“本地 Docker 能跑”推进到“线上可远程发布、可回滚、可排查、可备份”。本文按单台 VPS + Docker Compose 的最小可用生产方案编写，后续可平滑升级到镜像仓库、托管数据库和更完整的可观测体系。

## 当前推荐架构

第一阶段建议保持简单：

| 层级 | 工具 | 用法 |
|------|------|------|
| 代码托管与 CI | GitHub Actions | PR 自动跑后端测试、前端构建；main 分支才允许部署 |
| 远程发布 | SSH + Docker Compose | GitHub Actions 通过 SSH 到服务器执行部署脚本 |
| 反向代理/HTTPS | Caddy | 使用 `deploy/Caddyfile.prod`，自动 HTTPS，转发 `/api` 和 `/ws` |
| 运行时 | Docker Compose | 使用 `docker-compose.prod.yml` 跑 caddy/api/worker/postgres/redis/minio |
| 数据库迁移 | Alembic | 每次部署执行 `alembic upgrade head` |
| 健康检查 | `/health/ready` | 检查 API、PostgreSQL、Redis |
| 日志 | Docker logs | 先用 `docker compose logs`，业务稳定后再接日志平台 |
| 备份 | `pg_dump` + MinIO volume 备份 | 每日定时备份到服务器外部存储 |
| 私有维护通道 | Tailscale 或 SSH tunnel | MinIO 控制台、数据库维护、临时排障不暴露公网 |

第二阶段再考虑：

- GHCR 或 Docker Hub：CI 构建镜像，服务器只拉镜像，不在服务器构建。
- Sentry：前后端异常追踪。
- Uptime Kuma：外部健康检查和告警。
- Restic/Rclone：加密备份到 Cloudflare R2、Backblaze B2、S3 或 NAS。
- 托管 PostgreSQL/Redis/R2：减少自管数据层负担。

## 远程维护工具清单

### 必备

- `ssh`：远程进入服务器。
- `git`：服务器拉取代码。
- `docker` / `docker compose`：服务编排。
- `ufw`：只开放 `22/80/443`。
- `fail2ban`：降低 SSH 暴力破解风险。
- `curl`：健康检查。
- `pg_dump` / `psql`：数据库备份与检查。

### 建议安装

- `htop`：观察 CPU/内存。
- `ncdu`：定位磁盘占用。
- `jq`：处理 JSON 输出。
- `rsync`：传输备份或临时文件。
- `restic` 或 `rclone`：把备份推到服务器外部。
- `tailscale`：建立私有运维网络，减少公网暴露面。

### 谨慎使用

- Portainer：可以做 Docker UI，但不要直接暴露公网；只通过 Tailscale 或 SSH tunnel 访问。
- Watchtower：自动更新容器省事，但生产环境不建议无审核自动升级业务镜像。

## 服务器目录约定

建议把项目固定放在：

```bash
/opt/immigration-app
```

目录结构：

```text
/opt/immigration-app
├── .env                         # 只保存在服务器，不提交 Git
├── docker-compose.prod.yml
├── deploy/Caddyfile.prod
├── frontend/dist                # 前端构建产物，Caddy 直接读取
├── backups                      # 本地临时备份目录
└── scripts                      # 可选：部署/备份脚本
```

`.env` 只放在服务器和受控密码库中。GitHub Actions 不需要保存完整 `.env`，只保存 SSH 部署所需 secret。

## GitHub Secrets

在 GitHub 仓库设置 `Settings -> Secrets and variables -> Actions`：

| Secret | 用途 |
|--------|------|
| `PROD_HOST` | 服务器公网 IP 或域名 |
| `PROD_USER` | 部署用户，例如 `deploy` |
| `PROD_SSH_KEY` | 部署用户私钥 |
| `PROD_PORT` | SSH 端口，默认 `22` |
| `APP_DOMAIN` | 线上域名，例如 `app.example.com` |

生产环境变量如 `SECRET_KEY`、`POSTGRES_PASSWORD`、`LLM_API_KEY`、`STORAGE_SECRET_KEY` 不建议放进部署 workflow。它们保留在服务器 `/opt/immigration-app/.env`，由 `docker-compose.prod.yml` 的 `env_file: .env` 读取。

GitHub Actions 的 production environment 建议开启 required reviewers。这样 main 分支合并后仍需要手动批准才会发布。

## CI/CD 流程

### PR 阶段

每个 PR 必须完成：

1. 后端依赖安装：`pip install -r backend/requirements-dev.txt`
2. 数据库迁移：`alembic upgrade head`
3. 后端测试：`pytest tests/ -v --tb=short`
4. 前端构建：`npm ci && npm run build`

当前 `.github/workflows/ci.yml` 已经覆盖这些基础步骤。注意测试依赖必须使用 `requirements-dev.txt`。

### main 发布阶段

推荐最小发布脚本：

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

关键点：

- 先 `build` 新镜像。
- 先启动数据层。
- 再用新代码执行 `alembic upgrade head`。
- 最后启动业务服务。
- 部署成功必须通过 `/health/ready`。

### 可选 GitHub Actions 部署片段

可以在现有 workflow 的 deploy job 中替换占位命令：

```yaml
  deploy-vps:
    needs: [test-backend, test-frontend]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    environment: production
    steps:
      - uses: actions/checkout@v4
      - name: Deploy over SSH
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.PROD_HOST }}
          username: ${{ secrets.PROD_USER }}
          key: ${{ secrets.PROD_SSH_KEY }}
          port: ${{ secrets.PROD_PORT || 22 }}
          script: |
            export APP_DOMAIN="${{ secrets.APP_DOMAIN }}"
            cd /opt/immigration-app
            bash scripts/deploy.sh
```

如果不想依赖第三方 action，也可以直接用 `ssh` 命令，把私钥写入临时文件后执行远程脚本。

## 发布前检查

每次上线前确认：

- `git status` 干净，改动已提交。
- migration 已经写好，且本地跑过 `alembic upgrade head`。
- 后端测试通过。
- 前端构建通过。
- `.env.example` 新增变量已同步。
- 涉及 DB 字段删除、enum 变更、数据迁移时，先备份数据库。
- 涉及 LLM、文件解析、Celery 队列时，确认 worker 已重启。

## 发布后检查

```bash
docker compose -f docker-compose.prod.yml ps
curl -fsS https://app.example.com/health/ready
docker compose -f docker-compose.prod.yml logs --tail=100 api
docker compose -f docker-compose.prod.yml logs --tail=100 worker
docker compose -f docker-compose.prod.yml exec api alembic current
```

前端检查：

- 登录页打开正常。
- 管理员能登录系统后台。
- 文件上传、解析弹窗、审计底稿生成入口能打开。
- 上传小文件并触发后台解析后，当前审计项目「Agent 运行记录」能看到文件解析记录、诊断信息和提取事实数。
- 对一条事实提交异议重解析后，Agent 运行记录能看到来源文件、原事实、新事实和失败原因字段。
- 选择少量确认事实生成报告后，审计底稿生成记录能显示策略名、知识库标题、事实依据和生成版本。
- 顶部告警历史能看到解析、重解析、审计底稿生成、翻译等成功/失败记录；记录名称应是原始文件名、事实内容摘要或底稿标题，而不是操作名称。
- 设置页「通知偏好/告警偏好」中能按类别分别关闭弹出或历史记录；后台任务提交提示应和其他类别一样受弹出/历史开关控制。
- `/api/docs` 可访问，生产环境若不想暴露可单独加访问控制。

## 回滚方法

优先回滚代码，不自动回滚数据库：

```bash
cd /opt/immigration-app
git fetch --tags
git checkout <previous-good-tag-or-commit>

cd frontend
npm ci
npm run build
cd ..

docker compose -f docker-compose.prod.yml up -d --build api worker caddy
curl -fsS https://${APP_DOMAIN}/health/ready
```

数据库 downgrade 只有在 migration 明确支持且已经测试时才执行：

```bash
docker compose -f docker-compose.prod.yml exec api alembic downgrade -1
```

对生产数据库，优先使用“向前修复 migration”而不是随手 downgrade。

## 备份策略

### 数据库每日备份

```bash
mkdir -p /opt/immigration-app/backups/db
cd /opt/immigration-app

docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U postgres "${POSTGRES_DB:-immigration_db}" \
  > "backups/db/immigration_$(date +%F_%H%M).sql"
```

### MinIO 文件每日备份

```bash
mkdir -p /opt/immigration-app/backups/minio
cd /opt/immigration-app

docker run --rm \
  -v imigrationaplication_minio_data:/data:ro \
  -v "$PWD/backups/minio:/backup" \
  alpine tar czf "/backup/minio_$(date +%F_%H%M).tgz" /data
```

### 推荐 cron

```cron
15 3 * * * /opt/immigration-app/scripts/backup-db.sh >> /var/log/immigration-backup.log 2>&1
45 3 * * * /opt/immigration-app/scripts/backup-minio.sh >> /var/log/immigration-backup.log 2>&1
```

备份必须同步到服务器外部。只放在同一台 VPS 上，只能防误删，不能防磁盘损坏或服务器丢失。

## 常用排障命令

### API 不可用

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=200 api
curl -v https://${APP_DOMAIN}/health/ready
```

### Worker 不处理任务

```bash
docker compose -f docker-compose.prod.yml logs --tail=200 worker
docker compose -f docker-compose.prod.yml exec redis redis-cli -n 1 llen celery
docker compose -f docker-compose.prod.yml restart worker
```

### Agent 任务卡在处理中

先在前端打开当前审计项目的「Agent 运行记录」，确认任务状态、更新时间和错误信息。后台进一步检查：

```bash
docker compose -f docker-compose.prod.yml logs --tail=300 worker
docker compose -f docker-compose.prod.yml logs --tail=200 api
docker compose -f docker-compose.prod.yml exec redis redis-cli -n 1 llen celery
docker compose -f docker-compose.prod.yml exec postgres psql -U postgres -d immigration_db \
  -c "select task_type,status,updated_at,error_message from agent_tasks order by updated_at desc limit 20;"
```

处理原则：

- 如果任务已超过 `AGENT_TASK_QUEUED_TIMEOUT_MINUTES` 或 `AGENT_TASK_PROCESSING_TIMEOUT_MINUTES`，下一次打开相关页面或重新触发入口时会自动释放。
- 释放后的任务会显示 `agent_task_timeout`，按钮恢复后可重新发起。
- 不要直接在数据库里把任务改成完成；需要人工修复时，应只把明显卡死的旧任务标记为 `failed` 并记录原因。
- 如果 Worker 持续没有消费 Redis 队列，优先重启 `worker`，再检查 Redis 和模型 Provider。

### 数据库连接异常

```bash
docker compose -f docker-compose.prod.yml exec postgres pg_isready -U postgres
docker compose -f docker-compose.prod.yml exec api alembic current
docker compose -f docker-compose.prod.yml logs --tail=100 postgres
```

### Redis/缓存异常

```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
docker compose -f docker-compose.prod.yml exec redis redis-cli info memory
docker compose -f docker-compose.prod.yml restart redis worker api
```

### 磁盘快满

```bash
df -h
docker system df
docker image prune -f
docker builder prune -f
```

不要删除 Docker volumes，除非你已经确认有可恢复备份。

## 安全基线

- SSH 禁止密码登录，只用 key。
- 新建非 root `deploy` 用户，加入 docker 组。
- 防火墙只开放 `22/80/443`。
- 数据库、Redis、MinIO API 不暴露公网。
- MinIO 控制台只通过 SSH tunnel 或 Tailscale 访问。
- `.env` 权限设为 `600`。
- `SECRET_KEY` 至少 32 位随机字符串。
- `POSTGRES_PASSWORD`、`STORAGE_SECRET_KEY`、`LLM_API_KEY` 不提交 Git。
- GitHub Actions production environment 开启人工审批。
- 系统管理员邮箱用 `SYSTEM_ADMIN_EMAILS` 管理，离职或交接时及时移除。

## 监控建议

最低配置：

- Uptime Kuma 监控 `https://app.example.com/health/ready`。
- 每日备份成功/失败通知。
- VPS 磁盘使用率超过 80% 告警。

进阶配置：

- Sentry：前端 JS 错误、后端异常、性能慢请求。
- 日志平台：Better Stack、Grafana Loki 或云厂商日志。
- 数据库慢查询：上线后如果数据量增大，再开启 `pg_stat_statements`。

## 升级路线

### 阶段 1：单机 Compose

适合早期真实使用。成本低，部署快。

### 阶段 2：CI 构建镜像

GitHub Actions 构建 API/Worker 镜像推送 GHCR，服务器只拉镜像：

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

优点是服务器更干净，发布更快，回滚也可以按镜像 tag。

### 阶段 3：托管数据层

把 PostgreSQL、Redis、对象存储迁到托管服务。应用层仍保留 Docker Compose 或迁移到 Railway/Fly.io/Render。

### 阶段 4：蓝绿或滚动发布

业务稳定、用户增多后再做。当前单台 VPS 阶段，健康检查 + 快速回滚已经够用。

## 参考资料

- GitHub Actions secrets: https://docs.github.com/en/actions/configuring-and-managing-workflows/creating-and-storing-encrypted-secrets
- Docker Compose production: https://docs.docker.com/compose/how-tos/production/
- Docker Compose CLI: https://docs.docker.com/reference/cli/docker/compose/
- Caddy reverse_proxy: https://caddyserver.com/docs/caddyfile/directives/reverse_proxy
