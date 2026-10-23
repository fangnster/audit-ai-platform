# AuditAI Implementation and Operations Guide

Updated: 2026-10-23

[中文技术文档](implementation.md) · [English README](../README.en.md) · [User guide](audit_user_manual.en.md) · [Compatibility and backup](naming_and_backup.md)

This English guide explains the existing architecture and workflow after the audit naming change. The detailed Chinese implementation document retains the original engineering references and operational instructions.

## Change boundary

AuditAI adapts the existing application through audit branding, interface text, prompts and documentation. It preserves the API routes, database model, Alembic migration sequence, queue architecture, access rules and deployment resource names. It adds no audit certification, automatic audit opinion, standards-compliance engine or organization-level approval workflow.

The user-facing flow remains evidence upload → manual AI parsing → human fact review → asynchronous drafting → human review and follow-up. Existing databases and object storage do not need to be renamed.

## Architecture

```text
React 18 + TypeScript + Vite
  → FastAPI /api/v1
    → PostgreSQL 16: users, projects, facts, drafts and task records
    → Redis 7: list/LLM caches and Celery broker/result backend
    → S3-compatible storage: MinIO or a remote provider
    → Model provider: MiniMax / OpenAI-compatible / Claude / Gemini / Ollama
  → Celery Worker: parsing, re-parsing, drafting and rewriting
  → Caddy in production: HTTPS, frontend files, /api and /ws proxy
```

The ORM is SQLAlchemy; Alembic manages schema changes. Document extraction uses PyMuPDF, python-docx and Tesseract OCR. The model abstraction is the project's `LLMService` in `backend/app/llm/provider.py`.

## Implemented capabilities and boundaries

| Area | Current implementation |
|---|---|
| Account | Email/password registration and sign-in; profile, password, language, theme, alerts and model settings |
| Company/firm | Editable `firm_name` profile field; no organization-level business permission model |
| Engagements | Title, type, contact details, states, search, sorting, pagination, deletion and recovery |
| Evidence | Authenticated upload/download, built-in/custom document types, manually started background parsing |
| Facts | Multiple facts per document; confirmation, editing, translation, objections, re-parsing and follow-up tasks |
| Knowledge | Per-user items; title/tag search; prompt, template, sample and strategy categories |
| Drafting | Background generation, rewriting, translation, export and revision history |
| Tasks | Engagement follow-up tasks and cross-engagement Task Center |
| Agent logs | Per-engagement input, results, diagnostics, timings and failures |
| Administration | User/project search, user enablement, administrator roles, password reset and deletion |

The client portal, client sign-in, automatic evidence-request email, organization-shared knowledge, full-text/vector retrieval and simultaneous collaborative editing are not implemented. The firm profile field does not grant shared access.

## Code and data references

| Path or identifier | Purpose |
|---|---|
| `frontend/src/App.tsx` | Routes, login guard and administrator guard |
| `frontend/src/components/Layout.tsx` | Navigation, themes, language and administration entry |
| `frontend/src/pages/CasesPage.tsx` | Engagement listing and management |
| `frontend/src/pages/DocumentsPage.tsx` | Evidence, types and parsing |
| `frontend/src/pages/FactsPage.tsx` | Fact review and re-parsing |
| `frontend/src/pages/DraftsPage.tsx` | Drafts, rewriting, translation and revisions |
| `frontend/src/pages/KnowledgePage.tsx` | Personal audit knowledge |
| `backend/app/routers/` | API endpoints |
| `backend/app/agents/` | Agent prompt and execution logic |
| `backend/app/workers/` | Celery background tasks |
| `backend/migrations/versions/` | Authoritative schema migrations |
| `docs/database/schema.sql` | Reference schema snapshot, not a deployment initializer |

Compatibility identifiers such as `cases`, `lead_lawyer_id`, `lawyer_approved`, `LawyerTask`, `legal_rationale`, `criterion` and document-type IDs stay unchanged. The database and bucket defaults remain `immigration_db` and `immigration-docs`. See [the bilingual mapping](naming_and_backup.md) before integrating with the API.

## Access and configuration

Business access uses the signed-in user, engagement membership and system-administrator role. Engagement resources are checked against membership. Knowledge selection uses the current `user_id`. Legacy organization structures remain for compatibility and do not establish a shared business workspace.

`SYSTEM_ADMIN_EMAILS` bootstraps administrator access when a matching user registers or signs in. Saved web model settings override backend environment settings, which override defaults. Model keys are not returned in plaintext. Restart API and Worker after changing server-side `.env` values.

## Background workflow

1. Evidence upload validates membership and an enabled document type, stores the file and creates a `pending` document. Upload does not start a model request.
2. Manual parsing creates an `agent_tasks` record, marks the document `parsing` and queues a Celery job.
3. The Worker extracts and chunks document text, builds the audit prompt and requests structured facts from the configured model.
4. Results are saved in `facts`; the document becomes `parsed` or `failed`. Inputs, diagnostics and errors are recorded.
5. Human review confirms or corrects facts. An objection queues fact re-parsing with the source, objection text and selected prompt/strategy references.
6. Drafting queues a job using selected facts, knowledge and user instructions. Draft sections retain revision snapshots during edits, rewrites and restores.

Duplicate jobs for the same document/fact are blocked while queued or processing. Generation also prevents another simultaneous queued/processing generation for the same engagement. Stale-task protection marks old jobs failed and releases the action for retry; late results from an old job must not overwrite the replacement.

Parsing and re-parsing accept Prompt Templates and Agent Strategies. Drafting and rewriting can use all knowledge types. All knowledge search matches titles and tags, not the body.

Input and output budgets limit facts, references, document text and tokens. Worker logs and `agent_tasks.error_message` help diagnose failures. Default environment examples use queued/processing protection of 10/18 minutes, draft soft/hard limits of 420/480 seconds and parse limits of 900/960 seconds; the runtime environment is authoritative.

## Local setup and validation

Use the [English quick start](../README.en.md#quick-start-with-docker). Bring up Docker Compose, apply `alembic upgrade head`, then check both health and readiness. For a complete manual development setup, see [local development](../README.en.md#local-development).

Required checks from the respective directories:

```bash
# From backend/
pip install -r requirements-dev.txt
pytest tests/ -v --tb=short
```

```bash
# From frontend/
npm ci
npm run build
```

Smoke-test the actual workflow: administrator/user sign-in, a small evidence upload, manual parsing, Agent logs, human fact confirmation and one generated draft section. Confirm that Worker logs do not show repeated errors.

## Production operations

The existing single-server deployment uses `docker-compose.prod.yml`, `deploy/Caddyfile.prod` and GitHub Actions in `.github/workflows/ci.yml`. Caddy provides HTTPS and serves the frontend build. Deploy API, Worker, PostgreSQL, Redis and object storage together; API-only deployment leaves background jobs unprocessed.

Keep the production `.env` on the server, set `DEBUG=false`, use private credentials and configure the model provider, storage, Redis, database, domain and administrator emails. Existing deployment examples use `/opt/immigration-app`; this path is retained to avoid unnecessary changes. Replace example hosts, users and credentials with your own configuration.

GitHub Actions deployment secrets documented by the project are `PROD_HOST`, `PROD_USER`, `PROD_SSH_KEY`, `PROD_PORT` and `APP_DOMAIN`. Runtime business secrets remain in the server environment. The Chinese [deployment guide](deployment_remote_economical.md) and [maintenance runbook](remote_maintenance_runbook.md) retain the complete deployment, firewall, SSH and rollback examples.

From the deployment directory, routine checks include:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 api worker
docker compose -f docker-compose.prod.yml exec api alembic current
```

Run migrations as part of deployment, then verify `/health/ready` through the configured application URL. Avoid exposing PostgreSQL, Redis or MinIO administration directly; use the documented private maintenance channel.

Back up PostgreSQL with `pg_dump` and back up object storage separately. Keep copies outside the server and verify restoration. The local pre-change Git bundle preserves program history, not live business data or secret configuration.

When a job fails, inspect its Agent Run Log and `agent_tasks.error_message`, then check Worker availability, Redis connectivity, provider credentials, model IDs, rate limits, timeouts and input sizes. Reduce the task scope before retrying a model request that exceeded its budget.

## Documentation maintenance

Chinese technical/deployment instructions retain their established paths. English entry points are `README.en.md`, `docs/audit_user_manual.en.md` and this file. The [bilingual naming and backup note](naming_and_backup.md) records all retained terminology and the original source archive.

Public copies live under `frontend/public/docs/`. When changing a source document, update its mirrored copy and rewrite relative links for that flat public directory. Publishing documentation to GitHub makes these files available in the public repository; it does not by itself deploy the running application.
