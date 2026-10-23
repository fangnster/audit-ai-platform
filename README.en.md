# AuditAI — AI Agent Audit Workspace

[简体中文](README.md) · [Public repository](https://github.com/fangnster/audit-ai-platform)

AuditAI organizes audit projects, evidence, verified facts, working papers, report drafts and follow-up tasks. It reuses the existing application and workflow with audit terminology and prompts.

AI output is a draft for human review. The application does not perform audit attestation, certify compliance or issue an audit opinion automatically.

## Workflow

```text
Create an audit project → Upload evidence → Manually start AI parsing
→ Review and confirm facts → Select relevant facts and knowledge
→ Generate one working-paper or report section → Review, rewrite and translate
→ Track missing evidence and follow-up tasks → Export reviewed drafts
```

- Projects support contact information, statuses, search, sorting, pagination, soft deletion and recovery. At least one contact email or phone number is required.
- Evidence supports built-in and custom document types. Uploading a file does not automatically parse it.
- Facts support confirmation, editing, translation, objections and asynchronous re-parsing.
- Knowledge items belong to the current user. Search matches titles and tags. Parsing and re-parsing use prompt templates and Agent strategies; drafting and rewriting can use all knowledge types.
- Parsing, re-parsing, drafting and rewriting run in Celery. Project-specific Agent run records show inputs, outputs, diagnostics and failures.
- Task Center covers follow-up work across projects; project tasks cover the current project. Alerts retain recent success/failure history according to the user's preferences.
- System administrators manage users and projects. Company/firm names are profile fields; they do not establish organization-level permissions or shared knowledge.
- The interface supports Chinese and English, plus light and dark themes.

## Documentation

| Topic | 中文 | English |
|---|---|---|
| Project overview and quick start | [README](README.md) | This document |
| Audit operator guide | [审计操作手册](docs/audit_user_manual.md) | [Audit user guide](docs/audit_user_manual.en.md) |
| Architecture, API and operations | [技术实现](docs/implementation.md) | [Implementation guide](docs/implementation.en.md) |
| Naming compatibility and backup | [中英文说明](docs/naming_and_backup.md) | [Bilingual guide](docs/naming_and_backup.md) |
| Product scope | [产品需求](docs/product_requirements.md) | [Implemented capabilities](docs/implementation.en.md#implemented-capabilities-and-boundaries) |
| Local deployment | [本地部署](docs/deployment_local_economical.md) | [Local development](#local-development) |
| Production deployment and maintenance | [远程部署](docs/deployment_remote_economical.md), [维护手册](docs/remote_maintenance_runbook.md) | [Production operations](docs/implementation.en.md#production-operations) |
| V1 overview | [平台说明](AI%20Agent%20审计协作平台%20V1.md) | [Workflow](#workflow) |

Public documentation is kept in the repository's `docs/` directory and mirrored under `frontend/public/docs/` for the application's `/docs/` page.

## Technology

| Layer | Implementation |
|---|---|
| API | Python 3.11, FastAPI, SQLAlchemy, Alembic |
| Background work | Celery |
| Database | PostgreSQL 16 |
| Cache and queues | Redis 7 |
| Storage | Local MinIO or an S3-compatible provider |
| Language models | MiniMax, OpenAI-compatible, Claude, Gemini or Ollama |
| Frontend | React 18, TypeScript, Vite |
| Deployment | Docker Compose; Caddy for production HTTPS |

## Quick start with Docker

Prerequisites: Git 2.x, Docker 24+ and Docker Compose 2.20+. Frontend development also uses Node.js 20.x; backend development uses Python 3.11+.

```bash
git clone https://github.com/fangnster/audit-ai-platform.git
cd audit-ai-platform
cp .env.example .env
```

Edit `.env` with a valid model configuration and a private application signing key:

```env
LLM_PROVIDER=minimax
LLM_MODEL=MiniMax-M2.7
LLM_BASE_URL=https://api.minimax.chat/v1
LLM_API_KEY=replace-with-your-provider-key
SECRET_KEY=replace-with-a-private-random-key-at-least-32-characters
```

Use the provider/model settings appropriate to your account. Docker Compose supplies the local PostgreSQL, Redis and MinIO service addresses.

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose ps
```

If the API is still starting, wait for it to become available before running the migration command. Alembic migrations are the source of truth for the schema; `docs/database/schema.sql` is a reference snapshot.

| Service | URL |
|---|---|
| Web application | <http://localhost:5173> |
| Swagger API documentation | <http://localhost:8000/api/docs> |
| ReDoc | <http://localhost:8000/api/redoc> |
| Health | <http://localhost:8000/health> |
| Database/Redis readiness | <http://localhost:8000/health/ready> |
| MinIO console | <http://localhost:9001> |

Local MinIO development credentials are `minioadmin` / `minioadmin123`. Production credentials must be configured separately.

To bootstrap a system administrator, set `SYSTEM_ADMIN_EMAILS=admin@example.com` in the backend environment, restart API and Worker if the environment changed, then register or sign in using that email address.

## Local development

Start infrastructure from the repository root:

```bash
docker compose up -d postgres redis minio
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
```

Change local backend service addresses in `backend/.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/immigration_db
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
STORAGE_ENDPOINT_URL=http://localhost:9000
```

Keep the model configuration and signing key configured in that file. Apply migrations and start the API:

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd backend
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info
```

Start the frontend in a third terminal:

```bash
cd frontend
npm ci
npm run dev
```

## Validation and routine commands

```bash
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v --tb=short
```

From `frontend/`:

```bash
npm ci
npm run build
```

Before production use, smoke-test sign-in, project creation, a small evidence upload, background parsing, fact confirmation, one draft section and the Agent run records.

From the repository root:

```bash
docker compose logs -f api worker
curl http://localhost:8000/health/ready
docker compose exec api alembic current
docker compose exec postgres psql -U postgres -d immigration_db
docker compose stop
```

Production uses `docker-compose.prod.yml` and `deploy/Caddyfile.prod`. Deploy both API and Worker; asynchronous operations need the Worker and Redis. Restart both services after changing server-side model configuration.

## Compatibility and the original archive

This is a terminology and prompt adaptation. Routes, tables, permissions, migrations, workflow states and technical deployment resource names remain compatible. For example, `case_type=EB1A` is displayed as Financial Audit, `lawyer_approved` means an auditor-confirmed fact, and the default database and bucket remain `immigration_db` and `immigration-docs`.

Before any documentation changes, the original local source was committed as `0aaa122a7f25f887e32acc47905e188bbdf57fca` and tagged `backup/pre-audit-20261023`. A Git bundle and source archive were also saved locally. See [the bilingual naming and backup guide](docs/naming_and_backup.md) for the full mappings and safe recovery commands. The local archives are not part of the public documentation.
