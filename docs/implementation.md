# AI Agent 移民律师协作平台 — 技术实现文档 V1.2

更新时间：2026-04-27
适用范围：当前仓库已实现功能。本文是当前唯一技术实现文档，用于说明系统架构、关键流程、数据模型、权限、缓存、部署和测试边界。

## 0. 当前实现校正

本系统已经从早期“组织/律所多租户协作平台”收口为更轻量的律师工作台：

- 公司/律所名称仍在注册页和设置页保留，可读可改，但仅作为用户资料字段。
- 组织/律所表结构保留为历史兼容壳，不参与案件、知识库、模型配置或权限筛选。
- 业务权限以“登录用户 + 案件成员 + 系统管理员角色”为主。
- 知识库只按律师本人 `user_id` 隔离，不按组织或律所共享。
- 文件解析、事实重解析、文案生成和 AI 重写都已改为后台 Agent 任务，并加入输入预算、知识库筛选、任务去重、超时释放、失败记录和可追踪运行记录，重点解决线上远端模型请求过慢和失败问题。
- 当前不提供客户门户、客户登录、自动邮件补件、团队权限审批、全文向量检索或多人实时协同编辑。

## 1. 产品与技术目标

ImmigrationAI 是面向移民律师和案件助理的 AI Agent 协作平台，用于把案件材料整理成可核验事实，再基于律师确认的事实生成或改写移民申请文案。

当前 V1 目标：

- 按案件集中管理文件、事实、任务、知识库和文案。
- 用 Agent 大模型辅助文件解析、事实重解析、翻译、文案生成和 AI 重写。
- 保留律师审核、事实确认、版本恢复和系统后台管理能力。
- 通过 Redis 缓存、数据库索引、输入预算和任务去重降低线上卡住概率。
- 以 Docker Compose 支持本地部署和经济型远程部署。

非目标：

- 不替代律师事实核验、法律判断和最终签字审核。
- 不在当前版本实现真正的组织/律所业务权限体系。
- 不提供客户门户或客户直接上传补材料入口。

## 2. 系统架构

```text
React 18 + TypeScript + Vite
  -> FastAPI API
    -> PostgreSQL 16：业务数据
    -> Redis 7：缓存 + Celery broker/result backend
    -> S3-compatible Storage：MinIO / Cloudflare R2 / Supabase Storage
    -> LLM Provider：MiniMax / OpenAI-compatible / Claude / Gemini / Ollama
  -> Celery Worker：文件解析、事实重解析、文案生成、AI 重写、RFI/Agent 任务
  -> Caddy：生产 HTTPS、静态前端、API 反向代理
```

生产推荐拓扑：

| 服务 | 实现 |
|------|------|
| 前端 | Vite 构建静态文件，生产由 Caddy 提供 |
| API | FastAPI，统一 `/api/v1` 路由 |
| Worker | Celery Worker，处理文件解析、事实重解析、文案生成、AI 重写等异步 Agent 任务 |
| 数据库 | PostgreSQL 16 |
| 缓存/队列 | Redis 7 |
| 文件存储 | MinIO 或 S3-compatible 远端存储 |
| 反向代理 | Caddy，负责 HTTPS 和同源入口 |

## 3. 技术栈

| 层次 | 当前实现 |
|------|----------|
| 前端框架 | React 18 + TypeScript + Vite |
| 路由 | React Router |
| 数据请求 | Axios + TanStack Query |
| 登录态 | Zustand |
| UI 反馈 | React Hot Toast + Lucide React |
| 后端框架 | Python 3.11 + FastAPI |
| ORM/迁移 | SQLAlchemy 2.0 + Alembic |
| 数据库 | PostgreSQL 16 |
| 缓存/队列 | Redis 7 + Celery |
| 文件存储 | MinIO / S3-compatible Storage |
| LLM 抽象 | `backend/app/llm/provider.py` 自研 `LLMService` |
| 文档解析 | PyMuPDF + python-docx + Tesseract OCR |
| 容器化 | Docker + Docker Compose |
| CI/CD | GitHub Actions |

说明：

- 当前没有使用 LiteLLM。
- 当前没有把 pgvector 作为业务检索依赖。
- 当前富文本能力以文案段落、版本和导出为主，TipTap 属后续规划。

## 4. 前端实现

核心目录：

| 路径 | 职责 |
|------|------|
| `frontend/src/App.tsx` | 路由定义、登录保护、管理员路由保护 |
| `frontend/src/components/Layout.tsx` | 主导航、主题、语言切换、管理员入口 |
| `frontend/src/pages/CasesPage.tsx` | 案件列表、搜索、排序、分页、回收站 |
| `frontend/src/pages/CaseDetailPage.tsx` | 案件详情入口 |
| `frontend/src/pages/DocumentsPage.tsx` | 文件上传、文档类型设置、解析弹窗、下载/导出 |
| `frontend/src/pages/FactsPage.tsx` | 事实审核、异议、重解析、翻译、补材料任务 |
| `frontend/src/pages/DraftsPage.tsx` | 文案生成、AI 重写、翻译、版本 |
| `frontend/src/pages/TasksPage.tsx` | 案件任务 |
| `frontend/src/pages/GlobalTasksPage.tsx` | 任务中心，跨案件任务 |
| `frontend/src/pages/AgentRunsPage.tsx` | 当前案件 Agent 运行记录 |
| `frontend/src/components/AgentRunLogPanel.tsx` | Agent 运行记录展示组件 |
| `frontend/src/pages/KnowledgePage.tsx` | 律师个人知识库 |
| `frontend/src/pages/SettingsPage.tsx` | 个人信息、公司/律所字段、主题、模型设置、密码 |
| `frontend/src/pages/AdminPage.tsx` | 系统后台 |
| `frontend/src/api.ts` | API 封装和错误处理 |
| `frontend/src/utils/llmError.ts` | 大模型错误可读化 |

前端实现原则：

- 页面直接面向律师工作流，不做营销首页。
- 事实、文件、文案、任务等列表提供搜索/排序/分页或回收站能力。
- 大模型失败时尽量展示可读错误，避免只显示网络异常。
- 解析和重解析弹窗保持知识库选择体验一致。
- 文件解析、事实重解析、文案生成和 AI 重写都可以在案件内 Agent 运行记录页追踪状态和结果。

## 5. 后端路由

| Router | 前缀 | 职责 |
|--------|------|------|
| `auth.py` | `/api/v1/auth` | 注册、登录、当前用户、个人信息、密码 |
| `cases.py` | `/api/v1/cases` | 案件 CRUD、搜索、排序、分页、回收站、成员 |
| `documents.py` | `/api/v1/documents` | 文件类型、上传、解析、下载、导出 |
| `facts.py` | `/api/v1/facts` | 事实列表、确认、异议重解析、翻译、删除 |
| `drafts.py` | `/api/v1/drafts` | 文案生成、重写、导出、版本、Agent 运行记录 |
| `tasks.py` | `/api/v1/tasks` | 待办任务、完成、恢复、删除 |
| `knowledge.py` | `/api/v1/knowledge` | 律师个人知识库 |
| `translation.py` | `/api/v1/translate` | 翻译 |
| `orgs.py` | `/api/v1/orgs` | 历史兼容组织壳和模型设置兼容入口 |
| `admin.py` | `/api/v1/admin` | 系统后台：概览、用户、案件、密码重置、删除 |
| `sessions.py` | `/api/v1/sessions` | 用户 UI 会话状态 |
| `ws.py` | `/ws/cases/{case_id}` | 案件 WebSocket 通道 |

## 6. 数据模型

核心表：

- `users`：账号、密码哈希、姓名、`firm_name`、系统管理员标记、profile。
- `organizations` / `org_members`：历史兼容结构，当前业务不依赖其权限。
- `cases` / `case_members`：案件与成员关系，业务权限以案件成员为准。
- `documents`：文件元数据、对象存储路径、解析状态、`doc_type`。
- `facts` / `fact_collaborations`：事实、确认状态、异议重解析记录。
- `knowledge_items`：律师个人知识库。
- `draft_sections` / `draft_revisions`：文案段落和历史版本。
- `client_tasks`：任务中心。
- `agent_tasks`：Agent 异步任务记录。
- `user_sessions`：前端会话状态。

当前迁移版本到：

```text
013_database_cache_indexes
```

数据库结构源头是 Alembic migration。`docs/database/schema.sql` 只是当前结构快照，用于阅读、比对和归档，不作为生产部署初始化脚本。

关键迁移：

| 迁移 | 作用 |
|------|------|
| `010_add_system_admin_users` | 增加系统管理员字段 |
| `011_add_user_firm_name` | 增加用户公司/律所字段 |
| `012_document_type_customization` | 文档类型从 enum 改为 varchar，支持用户自定义 |
| `013_database_cache_indexes` | 增加后台、知识库、事实、任务、Agent 查询索引 |

## 7. 权限模型

当前权限规则：

- 登录后才能访问业务接口。
- 案件相关资源通过 `ensure_case_member` 校验。
- 知识库查询只取当前律师 `user_id`。
- 系统后台通过 `SystemAdminUser` 依赖校验。
- 公司/律所字段不用于权限判断。

系统管理员保护：

- 不能删除当前登录管理员自己。
- 不能禁用最后一个启用中的系统管理员。
- 重置密码只能设置新密码，不能读取旧密码。
- 删除用户或案件时需要关联处理案件、文件、事实、文案、任务、知识库和对象存储文件。

## 8. 业务流程

### 8.1 注册与设置

1. 用户注册邮箱、密码、姓名和公司/律所名称。
2. 公司/律所名称写入 `users.firm_name`。
3. 设置页可修改姓名、电话、公司/律所名称、密码、主题和模型设置。
4. `SYSTEM_ADMIN_EMAILS` 中匹配的邮箱注册或登录后会获得系统管理员角色。

### 8.2 案件管理

1. 律师创建案件，填写标题、类型、客户姓名、客户邮箱或电话。
2. 客户邮箱和电话至少填写一个。
3. 案件列表支持搜索、排序、分页。
4. 案件可软删除、恢复、彻底删除。
5. 案件相关资源统一按案件成员校验。

### 8.3 文件上传与解析

上传入口：

```text
POST /api/v1/documents/cases/{case_id}/documents
```

流程：

1. 校验案件成员。
2. 校验文档类型是否为当前用户启用类型。
3. 上传到 S3-compatible storage。
4. 创建 `Document`，状态为 `pending`。
5. 清理文件、案件和后台缓存。

解析入口：

```text
POST /api/v1/documents/{doc_id}/parse
```

流程：

1. 律师手动点击「AI 解析」。
2. 弹窗输入提示词或选择知识库。
3. 调用 `release_stale_agent_tasks` 释放超时的同文件解析任务。
4. 检查同一文件是否已有 `queued/processing` 的 `fact_extract` 任务；若有则返回现有任务。
5. 创建 `agent_tasks` 记录，文档状态设为 `parsing`。
6. 投递 Celery `parse_document`，前端无需等待大模型返回。
7. Worker 读取原始文件 bytes 并写入临时文件。
8. `FactExtractionAgent.extract_facts` 抽取文本、分块、构造 prompt。
9. `LLMService.extract_json` 调用大模型。
10. JSON 数组写入 `facts`。
11. 文档状态更新为 `parsed` 或 `failed`，Agent 记录写入结果与诊断。

解析优化：

- `PARSE_MAX_CONTENT_CHARS`
- `PARSE_MAX_LAWYER_GUIDANCE_CHARS`
- `PARSE_MAX_FACTS`
- `PARSE_MAX_OUTPUT_TOKENS`
- `PARSE_TASK_SOFT_TIME_LIMIT_SECONDS`
- `PARSE_TASK_TIME_LIMIT_SECONDS`
- PDF 大文件优先抽取开头和结尾页。
- 文本会按 `PARSE_CHUNK_MAX_CHARS`、`PARSE_CHUNK_OVERLAP_CHARS`、`PARSE_MAX_CHUNKS` 分块处理。
- 简历/CV/个人履历会生成简历分区辅助信息，低产出时触发重试，并在覆盖率不足时做缺口检查。
- 解析诊断记录文本质量、分块数量、候选信号、覆盖率、潜在遗漏数量和告警。
- `原创成果` 等类型加入专门指导。
- 解析入口知识库只允许提示词模板和 Agent 策略。

### 8.4 文件类型自定义

接口：

```text
GET /api/v1/documents/types
PATCH /api/v1/documents/types
```

实现：

- 内置类型自动补齐。
- 用户可以新增自定义类型。
- 用户可以修改显示名、图标、启用/停用状态。
- `documents.doc_type` 使用 `varchar(100)` 保存类型 key。

内置类型包括：

- 证据材料
- 获奖证明
- 原创成果
- 专利
- 学术发表
- 引用数据
- 雇佣证明
- 媒体报道
- 专业组织
- 推荐信
- 申请信
- RFI/RFE 回复
- 其他

### 8.5 事实审核与异议重解析

事实能力：

- 确认/取消确认。
- 编辑。
- 翻译。
- 删除/恢复/彻底删除。
- 从事实创建补材料任务。
- 提出异议并重新解析。

事实异议重解析：

1. 律师点击「有异议」。
2. 页面保持原有输入异议意见风格。
3. 输入异议后再次点击重新解析。
4. 弹出与文件上传解析一致的知识库选择弹窗。
5. 只允许选择提示词模板和 Agent 策略。
6. 后端调用 `release_stale_agent_tasks` 释放超时的同事实重解析任务。
7. 检查同一事实是否已有 `queued/processing` 的 `fact_reparse` 任务；若有则返回现有任务。
8. 创建 `agent_tasks` 记录并投递 Celery `reparse_fact`。
9. Worker 结合原事实、异议意见、来源文档文本和知识库重新生成事实。
10. 重解析结果写回事实结构化数据和 Agent 运行记录。

### 8.6 知识库

知识库类型：

- 提示词模板。
- 文案模板。
- 范文。
- Agent 策略。

筛选规则：

- 只查询当前律师本人 `user_id` 下知识库。
- 不查询组织或律所知识库。
- 所有入口检索只依靠标题和标签。
- 不按正文内容检索。
- 文件解析/事实重解析只允许提示词模板和 Agent 策略。
- 文案生成/AI 重写允许全部知识库类型。

### 8.7 文案生成与 AI 重写

生成入口：

```text
POST /api/v1/drafts/cases/{case_id}/generate
```

流程：

1. 校验案件成员。
2. 校验知识库 ID 是否属于当前用户。
3. 检查同案件是否已有 `queued/processing` 生成任务。
4. 创建 `agent_tasks` 记录。
5. 投递 Celery `generate_drafts`。
6. Worker 查询事实、知识库、历史文案。
7. 构造压缩后的 prompt。
8. 调用 LLM。
9. 拆分为 `draft_sections`。
10. 更新 Agent 任务状态，清理缓存。

重写入口：

```text
POST /api/v1/drafts/sections/{section_id}/rewrite
```

重写会：

- 保存旧版本到 `draft_revisions`。
- 使用当前段落、律师指令、选中事实和知识库。
- 更新段落内容。
- 清理文案缓存。

生成预算：

- `DRAFT_MAX_FACTS`
- `DRAFT_MAX_FACT_CHARS`
- `DRAFT_MAX_FACT_QUOTE_CHARS`
- `DRAFT_MAX_KNOWLEDGE_ITEMS`
- `DRAFT_MAX_KNOWLEDGE_CHARS`
- `DRAFT_MAX_USER_PROMPT_CHARS`
- `DRAFT_GENERATION_MAX_TOKENS`
- `DRAFT_REWRITE_MAX_TOKENS`
- `DRAFT_TASK_SOFT_TIME_LIMIT_SECONDS`
- `DRAFT_TASK_TIME_LIMIT_SECONDS`

这些预算用于减少远端模型超时、上下文过长和返回过长导致的失败。

文案生成和 AI 重写状态：

- 同一案件已有 `draft_generate` 的 `queued/processing` 任务时，后端返回现有任务，避免重复生成。
- Worker 开始前和 LLM 返回后都会检查任务是否仍处于活动状态；已被超时释放或人工取消的旧任务不会写回结果。
- 缺少案件、事实、文案段落等必要输入时，任务标记为 `failed`，错误写入 `error_message`。
- 成功任务写入版本、使用事实数量、知识库引用数量等结果。
- 关联事实、策略、知识库、文件和文案标题在前端以可读文本展示，机器 ID 会被过滤或压缩。

### 8.7.1 Agent 运行记录

入口：

```text
GET /api/v1/drafts/cases/{case_id}/agent-tasks
```

前端入口位于每个案件内，在「案件任务」后面，只显示当前案件的 Agent 状态。

分类：

- 文件解析和重解析：`fact_extract`
- 事实重解析：`fact_reparse`
- 文案生成和 AI 重写：`draft_generate`、`rewrite_section`、`rfi_generate`

展示规则：

- 支持更新时间升序/降序。
- 当前接口默认返回最近 20 条，前端按每页 10 条分类分页。
- 每条记录展示状态、模型、耗时、输入、结果与诊断。
- `human_context` 会把文件名、事实名、文案标题、策略名、知识库标题等关联上下文转成人能阅读的文本。
- 文案生成和 AI 重写中的事实依据按普通换行展示，不使用醒目的特殊卡片。

超时释放：

- `AGENT_TASK_QUEUED_TIMEOUT_MINUTES`
- `AGENT_TASK_PROCESSING_TIMEOUT_MINUTES`

`release_stale_agent_tasks` 会把超过保护时间仍处于 `queued/processing` 的任务标记为 `failed`，写入 `agent_task_timeout`，并释放前端按钮。文件解析任务被释放时，同步把文档 `parse_status` 从 `parsing` 改为 `failed`。

### 8.8 翻译

翻译能力：

- 事实和文案可中英互译。
- 后端限制输出 token，并使用低温度。
- 翻译结果有短缓存，重复翻译同一内容时加速。
- 失败时通过 `readableLlmError` 展示可读错误。

### 8.9 任务中心

任务能力：

- 案件内任务和全局任务。
- 新建、编辑、审批、完成、重开、删除、恢复。
- 排序、缓存和跨案件查看。
- Agent 自动生成和律师手动创建任务均可跟踪。

### 8.10 系统后台

后台入口：

```text
/admin
```

接口前缀：

```text
/api/v1/admin
```

能力：

- 系统概览统计。
- 用户搜索、排序、分页。
- 案件搜索、排序、分页。
- 用户启用/停用。
- 授予或取消系统管理员角色。
- 重置用户密码。
- 删除用户。
- 删除案件。

第一个管理员：

```env
SYSTEM_ADMIN_EMAILS=admin@example.com
```

匹配邮箱的用户注册或重新登录后会被提升为系统管理员。

## 9. LLM Provider

核心文件：

```text
backend/app/llm/provider.py
```

支持 Provider：

- MiniMax
- OpenAI-compatible
- Claude
- Gemini
- Ollama

配置优先级：

```text
网页保存的模型设置 > 环境变量 > 程序默认值
```

安全与稳定性：

- API Key 不在前端明文展示。
- 模型输出统一清理 `<think>...</think>`。
- `extract_json` 使用低温度和 token 限制。
- 解析、翻译、文案生成、重写分别设置预算。
- LLM 短 TTL 缓存减少重复请求。
- 远端错误通过可读错误返回给前端。

## 10. 缓存与数据库优化

缓存文件：

```text
backend/app/services/cache.py
```

缓存策略：

- Redis 异步和同步客户端复用连接。
- `delete_pattern` 使用 `scan_iter` 分批删除。
- API shutdown 时关闭缓存连接。
- Redis 异常时列表缓存降级为数据库查询。
- Celery 队列依赖 Redis，生产必须监控。

已缓存：

- 案件列表、回收站、详情。
- 文件列表。
- 事实列表、回收站。
- 文案列表、回收站。
- 任务列表。
- 知识库列表、回收站。
- 后台概览、用户列表、案件列表、最近案件。
- LLM 短 TTL 结果缓存。
- 翻译短缓存。

索引优化：

- 案件列表、文件列表、事实列表、任务列表。
- 知识库按 `user_id/type/deleted_at/updated_at` 查询。
- 后台用户/案件分页排序。
- Agent 任务状态查询。
- 软删除和回收站查询。

## 11. 部署实现

### 11.1 本地开发

使用：

- `docker-compose.yml`
- API：`uvicorn --reload`
- 前端：Vite dev server
- MinIO 控制台

常用命令：

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
curl http://localhost:8000/health/ready
```

### 11.2 远程生产

使用：

- `docker-compose.prod.yml`
- `deploy/Caddyfile.prod`
- Caddy 同源提供前端和 API。
- API/Worker 使用同一 backend image。
- 每次发布执行 `alembic upgrade head`。

生产要点：

- API 和 Worker 必须同时部署。
- Redis 必须稳定。
- PostgreSQL、Redis、MinIO 不应暴露公网。
- `.env` 保留在服务器和密码库，不提交仓库。
- GitHub Actions 只保存 SSH 部署所需 secret。

## 12. CI/CD

CI 文件：

```text
.github/workflows/ci.yml
```

当前流程：

- 后端启动 PostgreSQL 和 Redis service。
- 安装 `backend/requirements-dev.txt`。
- 执行 Alembic migration。
- 运行后端测试。
- 前端执行 `npm ci` 和 `npm run build`。

远程部署建议：

- PR 只跑测试和构建。
- main 分支合并后通过 SSH 到服务器执行部署脚本。
- 部署脚本执行 `git pull`、构建镜像、启动服务、迁移数据库、健康检查。

## 13. 线上避免卡住的实现原则

已经实现：

- 文案生成任务去重，避免重复点击造成并发堆积。
- 文件解析和事实重解析按同一文件/同一事实去重，避免重复排队。
- Agent 超时释放机制会自动失败长时间卡住的排队或处理中任务，并允许重新触发。
- Worker 在 LLM 调用返回后再次检查任务状态，避免旧任务晚返回后覆盖新结果。
- 解析、生成、重写和翻译都有输入和输出预算。
- 列表缓存减少数据库压力。
- 数据库索引覆盖后台、知识库、事实、任务等高频查询。
- Worker 任务失败会记录错误。
- 案件内 Agent 运行记录展示文件、事实、文案、策略和知识库的可读上下文，便于排查线上问题。
- 大模型输出清理 `<think>` 标签。

仍需操作层配合：

- 大文件解析尽量拆分。
- 扫描件尽量先 OCR 或转为可复制文本 PDF。
- 单次生成只选相关事实和少量知识库。
- 生成完整 petition letter 时应按章节分批生成。
- 远端模型超时或 429 时，不要连续重复点击。
- 管理员需要查看 API、Worker、Redis、案件内 Agent 运行记录和 `agent_tasks.error_message`。

## 14. 测试覆盖

当前测试目录：

```text
backend/tests
```

覆盖方向：

- 登录、注册、系统管理员。
- 案件与后台分页排序。
- 文件上传、下载、解析失败、文档类型自定义。
- 事实异议重解析。
- 文案拆分、生成 prompt、重写历史。
- Agent 任务超时释放、重复提交保护和后台解析投递。
- 组织兼容和模型设置。
- 翻译错误和缓存行为。
- 管理员删除用户和案件。

常用命令：

```bash
env DEBUG=false backend/.venv/bin/python -m pytest backend/tests
cd frontend && npm run build
git diff --check
```

如果本地 `.env` 里 `DEBUG` 不是布尔值，测试时用 `env DEBUG=false ...` 临时覆盖，避免 Pydantic 配置解析失败。

## 15. 当前限制与后续待办

当前限制：

- 文件解析仍由律师手动触发，非常大的扫描件可能受 OCR 和远端模型速度影响。
- 组织/律所没有真正协作权限模型。
- 客户门户未实现。
- 线上监控目前依赖健康检查、Docker 日志和测试。
- 文档解析质量取决于文件可读性和大模型稳定性。

后续待办：

- Agent 运行记录接口增加真正的后端分页、按类别过滤和更多检索条件。
- 增加客户门户和客户补材料入口。
- 恢复团队/律所级知识库共享与审批时，重新设计权限边界。
- 加入 Sentry、Uptime Kuma、外部备份告警。
- 对大 PDF、图片 OCR 增加页数选择和预览。
- 引入更细粒度的文案章节模板和 petition letter 组装导出。

## 16. 相关文档

- `README.md`：项目入口、快速启动和文档索引。
- `docs/product_requirements.md`：当前实现版产品需求文档。
- `docs/lawyer_user_manual.md`：律师操作手册。
- `docs/deployment_local_economical.md`：本地部署文档。
- `docs/deployment_remote_economical.md`：远程部署文档。
- `docs/remote_maintenance_runbook.md`：远程维护与 CI/CD 运维档案。
