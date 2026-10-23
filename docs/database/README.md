# 数据库结构快照

[English guide](../implementation.en.md) · [命名兼容与备份说明](../naming_and_backup.md)

本目录保存数据库结构参考快照。

## 文件

- `schema.sql`：由当前 PostgreSQL 数据库导出的结构快照，用于阅读、比对和归档。

## 维护规则

- 数据库结构的源头是 Alembic migration：`backend/migrations/versions/*.py`。
- 本目录的 `schema.sql` 不作为部署初始化脚本，不建议手动执行到生产库。
- 新增或修改表结构时，先创建 Alembic migration，再在需要归档时重新导出 `schema.sql`。
- 远程部署和本地部署都应使用 `alembic upgrade head` 应用结构变更。

## 推荐导出命令

Docker 本地环境可用：

```bash
docker compose exec postgres pg_dump -U postgres -d immigration_db --schema-only --no-owner --no-privileges > docs/database/schema.sql
```

如果数据库名、用户或容器名不同，请按 `.env` 和 `docker-compose.yml` 调整。
