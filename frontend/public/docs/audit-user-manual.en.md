# AuditAI User Guide

Updated: 2026-10-23

[中文操作手册](audit-user-manual.md) · [English README](readme.en.md) · [Naming and backup](naming-and-backup.md)

For auditors, audit assistants, report writers and system administrators. This guide describes implemented features. An “Auditor” in the interface is the business user responsible for verifying evidence and reviewing drafts; the application does not grant professional qualifications or issue audit opinions.

## 1. Working principles

Upload evidence first, extract facts second, confirm facts third, then generate a draft. Use only relevant, traceable facts in deliverables. AI text remains a draft until an authorized person reviews it. Work on one document, issue or report section at a time.

## 2. Five-minute walkthrough

1. Register or sign in.
2. Open Settings and check your name, phone and company/firm information.
3. Save and test the model Provider, Model, Base URL and API Key.
4. Create a test audit engagement from Audit Engagements.
5. Upload one or two clear documents and select their audit document types.
6. Manually start AI Parse with a short, specific instruction.
7. Open the fact library, inspect each useful fact against its source, edit it where needed and confirm it.
8. Open Audit Draft Generation, select relevant facts and generate one working-paper section.
9. Review the draft, then rewrite or translate if needed.
10. Record missing evidence and review actions in the engagement tasks. Use Task Center for work across engagements.

## 3. The engagement workflow

```text
Create engagement → Upload files → AI parse → Review and confirm facts
→ Select templates or strategies → Draft one section → Auditor review
→ Follow up missing evidence → Update facts and drafts → Finalize
```

Fact confirmation is a human review action. It does not establish that an audit procedure has been performed or that evidence is sufficient for an audit opinion.

## 4. Account, firm information and alerts

Sign in with email and password. Registration requires a company/firm name. Settings allows profile changes, password changes, light/dark theme selection and alert preferences. Changing a password requires the current password and confirmation of the new one.

Firm names are profile information. They do not share a knowledge library, grant organization permissions or change engagement access. System administrators have an additional administration entry in the sidebar.

Alert History shows recent success and failure notifications using source object names such as file, fact, draft or task titles. Settings can control popups and history separately by category; these preferences and the alert history are browser-local. For job diagnostics, open the engagement's Agent Run Log.

## 5. Model settings

Check four fields:

- Provider: for example, `minimax`, `openai`, `claude`, `gemini`, `ollama` or an OpenAI-compatible endpoint.
- Model: the provider's model ID.
- Base URL: the endpoint expected by the selected provider or gateway.
- API Key: your provider credential.

Configuration priority is saved web settings, then backend environment variables, then application defaults. The saved key is not returned in plaintext. Save before testing. After changing a server `.env`, restart both API and Worker so asynchronous jobs use the same configuration.

## 6. Engagements

Create an engagement with a title, audit type, contact name and at least one email address or phone number. Suggested titles are `Entity — 2026 Financial Audit`, `Entity — Internal Controls` or `Entity — Compliance Review`.

The existing status flow tracks intake, fact extraction, drafting, review and completion. Search, sorting, pagination, editing, soft deletion and recovery are available. Administrators have additional deletion capabilities.

Audit types are display labels for retained compatibility values: `EB1A` means Financial Audit; `EB1B`, Internal Audit; `NIW`, Compliance Audit; `O1A`, Operational Audit; `EB2`, IT Audit; `EB3`, Special Audit; and `H1B`, Other Audit. See [the complete mapping](naming-and-backup.md).

## 7. Uploading files and document types

Available types include Audit Evidence, Financial Statements, Internal Controls, Contracts and Agreements, Accounting Records, Transaction Details, Payroll and Personnel, External Information, Policies and Procedures, Business Processes, Confirmations and Representations, Audit Report, Audit Inquiry Response and Other.

You can customize type names, icons and availability, or add your own types. Existing custom types keep their saved values.

- Prefer readable PDFs, Word documents or clear images. OCR can help with scans.
- Split very large files and avoid combining unrelated evidence into one PDF.
- Include the entity, document type and date in filenames.
- Uploading does not start parsing; manually click AI Parse.
- The file list supports downloading originals and exporting the facts extracted from a document.

## 8. Knowledge library

Knowledge items belong to the current user. They are not shared automatically by organization or firm. All selection dialogs search titles and tags, rather than the full body.

Parsing and fact re-parsing accept Prompt Templates and Agent Strategies. Draft generation and AI rewriting can also use Document Templates and Samples. Give items searchable names and tags, such as `Financial audit — revenue cutoff parsing` with `financial audit, revenue, cutoff, parse`.

## 9. Parsing evidence

AI parsing can extract document-supported dates, amounts, currencies, parties, contract terms, approval records and exceptions. Ask for a limited number of verifiable facts. Do not ask parsing to determine an audit opinion, invent missing evidence or draft an entire report.

Example:

```text
Extract up to 8 verifiable facts relevant to the revenue cutoff review.
Preserve each transaction's date, amount, currency, counterparty and source.
Distinguish document statements from conclusions.
Flag missing information; do not invent it.
```

Internal-control example:

```text
Extract the control objective, responsible person, frequency, approval record
and exceptions. Distinguish the control policy from evidence of execution.
Do not treat a written requirement as proof that the control operated.
```

Confirmation example:

```text
Extract the responding party, confirmed balance, date and limitations.
Distinguish third-party confirmation from management representation.
Do not infer independent verification beyond the source document.
```

Keep parsing references to the one or two most relevant knowledge items. Jobs run in the background, so you can leave the page. The Agent Run Log shows status, extracted fact counts, text quality, chunks, coverage, warnings and failures. Duplicate parsing for a file already queued or processing is blocked. Stale jobs are marked failed and released for retry.

## 10. Reviewing facts and raising objections

Each fact can be confirmed, unconfirmed, edited, translated, deleted, restored or used to create a follow-up task. Verify the statement, date, amount, limitations and source before confirming it.

If a fact is wrong, submit a specific objection and choose relevant knowledge references for re-parsing. For example:

```text
The fact describes an approval policy as evidence that approval occurred.
Separate the policy requirement from the actual execution record.
If the file contains no approval record, state that the evidence is missing.
```

Re-parsing runs in the background and prevents duplicate work on the same fact. The Agent Run Log shows the original fact, replacement, source context, references and errors.

## 11. Drafting working papers and report sections

Confirm the engagement, select suitable facts and choose relevant knowledge before generating. Useful small drafting tasks include a revenue-test memo, control-execution summary, compliance finding, evidence-gap note, management-representation summary or audit inquiry explanation.

Example:

```text
Draft the revenue review working-paper section from the selected confirmed facts.
Explain the contract support, posting dates, amounts and evidence consistency.
Use only the provided facts and knowledge references.
Distinguish evidence, procedures, findings and unresolved questions.
Do not assert that a test was performed unless the selected facts support it.
```

Use approximately 6–15 relevant facts and 1–4 knowledge items as a starting point, within the server's configured budgets. Generate one objective or section at a time, then review and assemble the final report manually. Jobs run in Celery; another queued or processing generation job for the same engagement prevents a duplicate submission.

Draft sections can be edited, rewritten, translated, exported, deleted and restored. Edits, rewrites and restores retain version history. The Agent Run Log records generation inputs and outcomes.

## 12. AI rewriting

Use rewriting to improve an existing section without changing the evidence. Useful instructions include “make this more formal without adding facts,” “shorten to 300 words while retaining dates and amounts,” or “separate confirmed findings from unresolved matters.”

Choose a small number of relevant templates or strategies. After rewriting, check for invented facts, overstated certainty, deleted limitations, changed dates, amounts or entity names. Restore a previous version when necessary.

## 13. Translation

Translate one fact, paragraph or section at a time. Review entity names, accounting terms, contract titles, dates, amounts, currencies, identifiers, negatives and conditions. Preserve the source term where an exact translation matters. Human-check formal deliverables after translation.

## 14. Task Center, engagement tasks and Agent Run Log

Task Center lists work across engagements. Engagement tasks cover the current engagement, such as missing contracts, confirmation replies and review actions. Tasks support creation, status changes, completion, reopening, deletion and restoration.

Give each task a responsible person, due date, requested evidence and the audit objective it supports. Example: “Obtain September sales contracts and posting vouchers for the revenue cutoff review; due according to the engagement plan.”

Agent Run Log is separate from these follow-up tasks. It groups file parsing/re-parsing, fact re-parsing, and draft generation/rewriting. Expand a record to see its status, model, timestamps, duration, readable input context, results, diagnostics and failures. Alert History is a quick recap of recent messages; Agent Run Log provides job details for the current engagement.

## 15. System administration

Administrators can inspect system totals, search/sort/page users and engagements, enable or disable users, change administrator access, reset passwords and delete users or engagements with related data. A reset sets a new password; it does not reveal the old one.

Confirm appropriate database and file backups before administrative deletion. The application prevents deleting the current administrator and prevents leaving the system without an enabled administrator.

## 16. Reliable prompts

Specify a small task, relevant evidence, expected structure, language, length and boundaries:

```text
Generate only [section name] for [audit objective].
Use only the selected facts and knowledge references.
Cover [one or two core issues] in [word/paragraph limit].
Preserve evidence sources and limitations.
Do not invent vouchers, tests, references or standards.
Flag insufficient evidence and unresolved questions.
```

Clear sources, readable files and limited inputs improve reliability. Avoid selecting all facts and knowledge or requesting a full engagement analysis in one call.

## 17. Slow or failed jobs

1. Avoid repeatedly clicking the same parse or generate button.
2. Check Alert History for the affected file, fact or draft.
3. Open the engagement's Agent Run Log for job status and the failure message.
4. Reduce file size, fact count or knowledge references and retry after the job is released.
5. Test the model configuration in Settings.
6. Give an administrator the engagement name, source filename, operation time and error message.

Long-running queued or processing jobs are eventually failed by the configured protection limits so the operation can be retried. Administrators should check API, Worker, Redis, provider connectivity and `agent_tasks.error_message`, including rate limits, timeouts, invalid keys or context-length errors.

## 18. Human review checklist

Before using a draft, check that facts are supported, material evidence is included, confidence is not overstated, facts from different entities are not mixed, the audit objective is correct, and no standards or procedures were invented.

Before external delivery, also verify the audited entity, reporting period, identifiers, engagement scope, report recipient, evidence references, translation fidelity and consistency across sections. Fact confirmation and draft approval do not replace the audit procedures or review required by your organization.

## 19. Team conventions

Agree on engagement and file names, document categories, required evidence, fact-confirmation responsibilities, reviewer responsibilities, standard knowledge items, model-setting access, deletion responsibilities and who handles operational errors. Start with one or two engagements before expanding usage.

## 20. Handling evidence

Use infrastructure approved by your organization. Files may contain private or commercially sensitive data, and selected content is sent to the configured model provider. Keep contact information current for follow-up work. Do not use unrelated client materials to test a model. Route drafts through the organization's review process before sharing findings or reports externally.
