# 本地部署方案：办公室电脑/内网服务器 + Docker Compose

目标：最直接、最经济地在律所本地运行，数据留在本机或内网服务器。

## 方案选择

适合以下场景：

- 律所内部试用
- 不希望案件材料默认出公网
- 只有少量律师同时使用
- 有一台常开的办公室电脑、Mac mini、NAS 或 Linux 小主机

推荐硬件：

- 最低：4 核 CPU / 8 GB RAM / 100 GB SSD
- 更稳：8 核 CPU / 16 GB RAM / 500 GB SSD
- 系统：Ubuntu Server 最省心；macOS + Docker Desktop 也可用于小规模试用

如果要把大模型也本地化：

- 轻量试用：16 GB RAM，可跑 7B/8B 量化模型，速度和法律文案质量有限。
- 稳定可用：32 GB RAM + 12 GB 以上显存，适合 8B/14B 量化模型。
- 更好效果：64 GB RAM + 24 GB 以上显存，适合 32B 量化模型，成本明显提高。
- 没有独立显卡也能跑，但生成速度会明显变慢，不建议多人同时使用。

本地运行组件：

- PostgreSQL + pgvector
- Redis
- MinIO
- FastAPI API
- Celery Worker
- React 前端

大模型调用是本地部署的必要配置：

- 推荐：本地系统 + 外部大模型 API。数据库、文件、案件数据留在本地；模型调用时会把提示词、事实和文案上下文发送给模型服务。
- 完全本地化：本地系统 + 本地大模型服务，例如 Ollama。需要本地显卡/大内存，生成质量和速度取决于模型能力。
- 不配置大模型 API 时，上传、建案、任务等基础功能可用，但解析、翻译、事实异议重解析、文案生成等 Agent 功能不可用。

## 1. 最快启动方式

适合本机试用：

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api alembic upgrade head
```

`.env` 至少配置一个模型调用方式：

```env
# 方案 A：调用外部 OpenAI-compatible / MiniMax 网关
LLM_PROVIDER=minimax
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=你的模型APIKey

# 方案 B：调用本地 Ollama
# LLM_PROVIDER=ollama
# LLM_MODEL=llama3.1:8b
# LLM_BASE_URL=http://host.docker.internal:11434/v1
# LLM_API_KEY=
```

访问：

```text
前端：http://localhost:5173
API 文档：http://localhost:8000/api/docs
MinIO 控制台：http://localhost:9001
```

## 2. 大模型本地化部署

本方案用于“数据和模型调用都尽量不出本机/内网”的部署。最直接经济的做法是安装 Ollama，并通过 OpenAI-compatible 接口提供给本系统调用。

### 2.1 安装 Ollama

Linux：

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

macOS：

- 从 https://ollama.com/download 下载 macOS 安装包，将 Ollama 拖入 `Applications`。
- 启动 Ollama 后，在终端运行 `ollama -v` 确认 CLI 可用。
- macOS 建议使用 Sonoma 14 或更新版本。

启动服务：

```bash
ollama serve
```

如果使用 systemd，Linux 安装脚本通常会自动创建服务。可检查：

```bash
systemctl status ollama
```

### 2.2 下载模型

先用轻量模型验证链路：

```bash
ollama pull llama3.1:8b
```

如果机器资源更好，可再尝试：

```bash
ollama pull qwen2.5:14b
ollama pull qwen2.5:32b
```

模型选择建议：

| 机器资源 | 建议模型 | 适合用途 |
|----------|----------|----------|
| 16 GB RAM，无独显 | `llama3.1:8b` | 链路验证、简单翻译、轻量摘要 |
| 32 GB RAM，12 GB 显存 | `qwen2.5:14b` | 一般事实抽取、短文案草稿 |
| 64 GB RAM，24 GB 显存 | `qwen2.5:32b` | 较长文案生成、复杂重写 |

法律文案质量通常仍低于强云端模型。建议本地模型先用于解析、翻译、内部草稿；正式递交文案仍需律师严格审核。

### 2.3 配置系统调用本地模型

如果后端运行在 Docker 容器内、Ollama 跑在宿主机：

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=
```

如果后端和 Ollama 都在同一个 Linux 内网服务器，且容器无法访问 `host.docker.internal`，可改用宿主机网关地址或内网 IP：

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b
LLM_BASE_URL=http://192.168.1.20:11434/v1
LLM_API_KEY=
```

确认 Ollama 监听地址允许容器访问。Linux 可设置：

```bash
sudo systemctl edit ollama.service
```

写入：

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

然后重启：

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### 2.4 验证本地模型

宿主机验证：

```bash
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.1:8b","messages":[{"role":"user","content":"用一句话说明 EB-1A 是什么"}]}'
```

容器访问验证：

```bash
docker compose exec api python - <<'PY'
import httpx
payload = {
    "model": "llama3.1:8b",
    "messages": [{"role": "user", "content": "hello"}],
}
print(httpx.post("http://host.docker.internal:11434/v1/chat/completions", json=payload, timeout=60).text[:500])
PY
```

如果容器访问失败，用服务器内网 IP 替换 `host.docker.internal`。

### 2.5 内网模型网关

如果律所有多台应用服务器或未来要换 vLLM/TGI/LM Studio，可统一提供一个 OpenAI-compatible 网关：

```env
LLM_PROVIDER=openai
LLM_MODEL=your-local-model
LLM_BASE_URL=http://llm-gateway.internal:8000/v1
LLM_API_KEY=可为空或内网令牌
```

只要网关兼容 `/v1/chat/completions`，当前 `LLMService` 就可以调用。

## 3. 内网多人访问

在运行机器上查看内网 IP：

```bash
ip addr
```

假设服务器 IP 是 `192.168.1.20`，同一办公室网络内访问：

```text
前端：http://192.168.1.20:5173
API：http://192.168.1.20:8000/api/docs
```

将 `.env` 中 CORS 改成：

```env
CORS_ORIGINS=["http://192.168.1.20:5173","http://localhost:5173"]
```

然后重启：

```bash
docker compose restart api frontend
```

## 4. 本地生产化运行

如果希望不使用 Vite dev server，而是像正式系统一样运行：

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

如果在局域网内给多人用，建议给内网服务器配一个固定 IP，并把 `APP_DOMAIN` 设置为内网 DNS 名称，例如：

```env
APP_DOMAIN=immigration.local
CORS_ORIGINS=["http://immigration.local","http://192.168.1.20"]
```

没有内网 DNS 时，继续用开发版 `docker compose up -d` 更直接。

## 5. 本地安全建议

- 不要把 5432、6379、9000 暴露到公网。
- 办公网访问时，优先通过 VPN 或内网访问。
- 定期更新系统和 Docker。
- `.env` 中的 `SECRET_KEY`、数据库密码、MinIO 密码必须改掉默认值。
- 重要客户材料建议每天备份到加密移动硬盘或律所 NAS。
- 如使用外部大模型 API，需确认律所允许把提示词和案件事实发送给该 Provider；如不允许，改用内网模型网关或本地 Ollama。
- 如果开放 Ollama 到 `0.0.0.0:11434`，只允许内网/VPN 访问，禁止暴露公网。

本地运维检查：

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
docker compose logs -f api
docker compose logs -f worker
```

- Redis 用于 Celery、页面列表缓存和 LLM 短 TTL 缓存；Redis 停止会影响 Agent 队列。
- API 日志包含 `request_id`、路径、状态码和耗时；Worker 日志包含 Agent 任务开始、完成、失败和重试。
- 文档、事实、任务、文案、案件和会话接口按案件成员校验权限，便于本地演示时隔离不同案件数据。
- 每次升级代码后执行 `docker compose exec api alembic upgrade head`，确保新增索引已应用。

## 6. 本地备份

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

## 7. 本地方案成本

- 已有电脑/服务器：几乎零新增成本
- 新购小主机：一次性硬件成本
- 外部 LLM：按量付费，是本地部署最经济、效果最稳的默认选择
- 本地大模型：不再支付 API 调用费，但需要一次性硬件成本和运维成本；模型质量也要单独评估

## 8. 推荐结论

- 个人或 2-3 人试用：直接 `docker compose up -d`
- 律所内部长期试用：一台 Ubuntu 小主机 + Docker Compose + 外部 LLM
- 对数据外流极敏感：本地部署 + VPN + Ollama/内网模型网关，但要接受生成质量、速度和硬件成本折中

## 参考

- Ollama Linux 安装：https://docs.ollama.com/linux
- Ollama macOS 要求：https://docs.ollama.com/macos
- Ollama 服务环境变量与 `OLLAMA_HOST`：https://docs.ollama.com/faq
- Docker Compose Linux 安装：https://docs.docker.com/compose/install/linux/
