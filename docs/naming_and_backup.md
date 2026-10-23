# 审计命名兼容与本地备份 / Audit Naming Compatibility and Local Backup

更新时间 / Updated: 2026-10-23

[中文 README](../README.md) · [English README](../README.en.md) · [中文操作手册](audit_user_manual.md) · [English user guide](audit_user_manual.en.md)

## 调整范围 / Change scope

AuditAI 将原有的“创建项目 → 上传证据 → 解析事实 → 人工确认 → 起草 → 复核 → 跟踪补材料”流程用于审计。变更集中在产品名称、界面文案、审计提示词和公开说明，沿用现有程序结构、路由、数据库表、任务队列、权限规则和迁移体系。

AuditAI adapts the existing project → evidence → facts → human confirmation → drafting → review → follow-up workflow for audit work. Changes focus on branding, interface text, audit prompts and documentation. Existing routes, tables, background queues, permissions and migrations remain in place.

AI 输出是供审计人员核验的底稿或报告草稿。系统不自动实施鉴证、签发审计意见或证明符合某项审计准则；选择适用准则、实施程序和最终复核仍由使用者负责。

AI output is a working paper or report draft for human verification. The application does not automatically perform attestation, issue an audit opinion or certify compliance with an audit standard. Users remain responsible for the applicable standards, procedures and final review.

## 项目类型 / Project types

为了兼容原有数据，`case_type` 的存储值不变。下面是显示名称映射，而不是新的数据库枚举。

The stored `case_type` values stay unchanged for data compatibility. These are display mappings, not new database enum values.

| 存储键 / Stored key | 中文显示 | English display |
|---|---|---|
| `EB1A` | 财务审计 | Financial Audit |
| `EB1B` | 内部审计 | Internal Audit |
| `NIW` | 合规审计 | Compliance Audit |
| `O1A` | 运营审计 | Operational Audit |
| `EB2` | 信息技术审计 | IT Audit |
| `EB3` | 专项审计 | Special Audit |
| `H1B` | 其他审计 | Other Audit |

## 文件类型 / Document types

| 存储键 / Stored key | 中文显示 | English display |
|---|---|---|
| `evidence` | 审计证据 | Audit Evidence |
| `award` | 财务报表 | Financial Statements |
| `original_contribution` | 内部控制 | Internal Controls |
| `patent` | 合同与协议 | Contracts and Agreements |
| `publication` | 会计记录 | Accounting Records |
| `citation` | 交易明细 | Transaction Details |
| `employment` | 薪酬与人事 | Payroll and Personnel |
| `media` | 外部资料 | External Information |
| `membership` | 政策与制度 | Policies and Procedures |
| `resume` | 业务流程 | Business Processes |
| `reference_letter` | 函证与声明 | Confirmations and Representations |
| `petition_letter` | 审计报告 | Audit Report |
| `rfi` | 审计询证回复 | Audit Inquiry Response |
| `other` | 其他 | Other |

已保存的自定义文件类型和知识库内容按原值保留。名称切换不会把历史上传材料或历史事实自动转换成审计证据；使用者需要复核其适用性。

Saved custom document types and knowledge content retain their existing values. Renaming does not convert historical uploads or facts into suitable audit evidence; users should review their relevance.

## 保留的技术名称 / Retained technical names

| 原有标识 / Existing identifier | 审计中的含义 / Audit meaning |
|---|---|
| `cases`, `/api/v1/cases`, `case_id` | 审计项目 / Audit project |
| `lead_lawyer`, `lead_lawyer_id`, `lawyer`, `LawyerTask` | 项目负责人、审计人员及其任务 / Project lead, auditor and tasks |
| `lawyer_approved` | 已经审计人员确认的事实 / Auditor-confirmed fact |
| `firm_name` | 公司或审计机构资料字段，不授予组织权限 / Company or firm profile field; does not grant organization permissions |
| `draft_sections`, `draft_revisions`, `drafts` | 底稿与报告草稿章节及其版本 / Working-paper and report-draft sections and revisions |
| `legal_rationale`, `criterion` | 沿用字段承载审计依据或审计目标 / Existing fields carrying audit rationale or objectives |
| `intake`, `fact_extraction`, `drafting`, `review`, `submitted` | 项目从接洽到事实提取、起草、复核和完成的原有状态 / Existing project states from intake through extraction, drafting, review and completion |
| `immigration_db`, `immigration-docs` | 默认数据库和对象存储桶，避免切换到空库/空桶 / Existing database and bucket names to preserve data access |
| `/opt/immigration-app` | 部署文档沿用的服务器目录示例 / Existing example deployment directory |

本地原始目录名也可以继续保留为 `imigrationAplication`。新克隆的公开仓库目录默认是 `audit-ai-platform`；无须为了显示名称重命名现有数据库、存储桶或服务器目录。

The existing local directory may remain `imigrationAplication`. A new clone defaults to `audit-ai-platform`. Display naming does not require renaming an existing database, bucket or server directory.

## 文档修改前的本地备份 / Local backup before documentation edits

在修改文档之前，已经完成以下本地程序存档：

The original local program was archived before documentation edits:

| 项目 / Item | 存档 / Archive |
|---|---|
| 原始源码提交 / Original source commit | `0aaa122a7f25f887e32acc47905e188bbdf57fca` |
| 本地标签 / Local tag | `backup/pre-audit-20261023` |
| Git 历史备份 / Git bundle | `.local-backups/pre-audit-20261023.bundle` |
| 源码归档 / Source archive | `.local-backups/pre-audit-20261023.tar.gz` |

这些存档在执行本次变更的本机保存，Git bundle 已验证。备份标签和历史包不随审计版公开发布。源码归档用于程序恢复，不包含未纳入 Git 的 `.env`、数据库卷或上传文件；数据库与对象存储仍需按运维手册另行备份。

These archives are retained on the machine where the change was performed; the Git bundle was verified. The backup tag and history bundle are kept local rather than published with the audit version. The source archive does not include untracked `.env` files, database volumes or uploaded files. Back up database and object storage data separately using the maintenance runbook.

在原本机查看备份，或从 bundle 恢复到新目录，避免覆盖当前工作区：

Inspect the backup on the original machine, or restore the bundle into a new directory without overwriting the current workspace:

```bash
git show --stat backup/pre-audit-20261023
git bundle verify .local-backups/pre-audit-20261023.bundle
git clone .local-backups/pre-audit-20261023.bundle ../audit-original-backup
git -C ../audit-original-backup switch --detach backup/pre-audit-20261023
```

## 公开文档位置 / Public documentation locations

- [GitHub 仓库 / GitHub repository](https://github.com/fangnster/audit-ai-platform)
- [中文说明 / Chinese README](https://github.com/fangnster/audit-ai-platform/blob/main/README.md)
- [English README](https://github.com/fangnster/audit-ai-platform/blob/main/README.en.md)
- [文档目录 / Documentation directory](https://github.com/fangnster/audit-ai-platform/tree/main/docs)
- [应用内公开文档 / In-app public documentation source](https://github.com/fangnster/audit-ai-platform/tree/main/frontend/public/docs)

仓库内相对链接用于浏览源码，`frontend/public/docs/` 内镜像用于部署后的 `/docs/` 入口。公开文档仅包含通用配置示例；实际密钥、私有部署信息和本地备份包应保留在受控环境中。

Repository-relative links are for source browsing. Files mirrored under `frontend/public/docs/` serve the deployed `/docs/` entry. Public documentation contains generic configuration examples; actual credentials, private deployment details and local archive files stay in controlled environments.
