# 本地 Docker 部署：办公室电脑/内网服务器

目标：用 Docker Compose 在本机或内网服务器运行整套系统，让数据库、文件和任务队列留在本地。

适合：

- 个人或 2-3 人试用
- 律所内网演示和长期试运行
- 不希望案件材料默认放到公网云服务

推荐机器：

| 场景 | 建议配置 |
| --- | --- |
| 轻量试用 | 4 核 CPU / 8 GB RAM / 100 GB SSD |
| 稳定多人试用 | 8 核 CPU / 16 GB RAM / 500 GB SSD |
| 本地大模型 | 32 GB RAM 起步；如需更好效果，建议独立显卡 |

本地 Docker 会启动：

- PostgreSQL
- Redis
- MinIO
- FastAPI API
- Celery Worker
- React 前端

## 1. 快速启动

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
```

健康检查：

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
docker compose ps
```

## 2. 大模型配置

不配置大模型时，建案、上传、任务等基础功能可用；解析、翻译、事实重解析、文案生成等 AI 功能不可用。

### 外部模型 API，推荐默认方案

数据库和文件留在本地，AI 相关提示词和上下文会发送给模型服务。

```env
LLM_PROVIDER=minimax
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=你的模型APIKey
```

也可以填任何 OpenAI-compatible 网关：

```env
LLM_PROVIDER=openai
LLM_MODEL=your-model
LLM_BASE_URL=https://your-gateway.example/v1
LLM_API_KEY=你的APIKey
```

### 本地 Ollama，可选

适合希望模型调用也尽量留在本机/内网的场景，但速度和质量取决于硬件与模型。

安装并拉模型：

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

如果 Linux 容器访问不了 `host.docker.internal`，改用宿主机内网 IP：

```env
LLM_BASE_URL=http://192.168.1.20:11434/v1
```

必要时让 Ollama 监听内网：

```bash
sudo systemctl edit ollama.service
```

写入：

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

然后：

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

## 3. 内网多人访问

在服务器上查看内网 IP：

```bash
ip addr
```

假设服务器 IP 是 `192.168.1.20`，同一办公室网络访问：

```text
前端：http://192.168.1.20:5173
API：http://192.168.1.20:8000/api/docs
```

`.env` 中允许该来源：

```env
CORS_ORIGINS=["http://192.168.1.20:5173","http://localhost:5173"]
```

重启：

```bash
docker compose restart api frontend
```

## 4. 本地生产化运行，可选

如果希望像正式系统一样用一个入口访问，而不是 Vite dev server：

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

如果给办公室多人长期使用，建议给服务器固定 IP 或内网域名，例如：

```env
APP_DOMAIN=immigration.local
CORS_ORIGINS=["http://immigration.local","http://192.168.1.20"]
```

没有内网 DNS 时，直接使用开发版 `docker compose up -d` 更简单。

## 5. 常用运维命令

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose restart api
docker compose stop
docker compose down
```

升级代码后执行：

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
```

说明：

- Redis 用于 Celery 队列、页面缓存和 LLM 短 TTL 缓存。
- API 日志包含请求路径、状态码、耗时和 `request_id`。
- Worker 日志包含 AI 任务开始、完成、失败和重试。

## 6. 备份与恢复

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

## 7. 安全检查

- 不要把 PostgreSQL、Redis、MinIO、Ollama 直接暴露到公网。
- 办公网访问优先走内网或 VPN。
- 修改 `.env` 中的 `SECRET_KEY`、数据库密码、MinIO 密码。
- 重要客户材料建议每天备份到加密移动硬盘或律所 NAS。
- 使用外部大模型前，确认律所允许把提示词、案件事实和文案上下文发送给该 Provider。
- 如果必须避免模型调用出网，使用 Ollama 或内网模型网关。

## 推荐结论

- 个人试用：`docker compose up -d --build`
- 律所内网长期试用：Ubuntu 小主机 + Docker Compose + 外部模型 API
- 对数据外流极敏感：Docker Compose + VPN + Ollama/内网模型网关
