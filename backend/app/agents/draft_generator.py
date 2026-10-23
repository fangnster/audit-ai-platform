"""
Draft Generation Agent

Generates one strategy-driven, auditor-customized audit document
from selected case facts and knowledge references.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings
from app.audit_terms import audit_case_type_label
from app.llm.provider import LLMService

logger = logging.getLogger(__name__)


# Legacy constant/criterion keys are retained for storage and API compatibility.
# These are evidence-organization objectives, not a substitute for supplied audit standards.
EB1A_CRITERIA = {
    "criterion_1": "Scope, reporting period, entity, and source financial statements",
    "criterion_2": "Applicable policies, control responsibilities, and authorization",
    "criterion_3": "Recorded transactions, supporting documentation, and external evidence",
    "criterion_4": "Review, reconciliation, and control testing evidence",
    "criterion_5": "Existence, occurrence, and supporting contractual evidence",
    "criterion_6": "Completeness and accuracy of accounting records",
    "criterion_7": "Presentation, disclosure, and supporting schedules",
    "criterion_8": "Business processes, personnel responsibilities, and control operation",
    "criterion_9": "Amounts, valuation, payroll, and quantitative comparisons",
    "criterion_10": "Exceptions, risks, corrective actions, and follow-up evidence",
}

NIW_CRITERIA = {
    "criterion_1": "Audit scope, objectives, and applicable requirements supplied by the auditor",
    "criterion_2": "Procedures performed, source evidence, and identified exceptions",
    "criterion_3": "Evidence-supported findings, limitations, and follow-up actions for review",
}


CRITERION_FACT_CATEGORIES = {
    "criterion_1": {"award", "evidence", "other"},
    "criterion_2": {"membership", "evidence", "other"},
    "criterion_3": {"media", "publication", "citation", "evidence", "other"},
    "criterion_4": {"judge", "review", "peer_review", "evidence", "other"},
    "criterion_5": {"patent", "publication", "citation", "employment", "evidence", "other"},
    "criterion_6": {"publication", "citation", "evidence", "other"},
    "criterion_7": {"exhibition", "showcase", "evidence", "other"},
    "criterion_8": {"employment", "leadership", "evidence", "other"},
    "criterion_9": {"salary", "employment", "evidence", "other"},
    "criterion_10": {"commercial_success", "media", "evidence", "other"},
}

NIW_FACT_CATEGORIES = {
    "criterion_1": {"publication", "citation", "patent", "media", "evidence", "other"},
    "criterion_2": {"education", "employment", "publication", "patent", "award", "evidence", "other"},
    "criterion_3": {"employment", "media", "reference_letter", "evidence", "other"},
}


@dataclass
class EvidenceSource:
    document_id: str | None = None
    document_name: str | None = None
    page: int | str | None = None
    quote: str | None = None


def _truncate_text(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


@dataclass
class CaseFact:
    id: str | None
    category: str
    content: str
    source: EvidenceSource = field(default_factory=EvidenceSource)
    confidence: float = 1.0
    structured_data: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict) -> "CaseFact":
        structured = value.get("structured_data") or {}
        source = EvidenceSource(
            document_id=value.get("source_document_id") or structured.get("document_id"),
            document_name=structured.get("document_name") or structured.get("source"),
            page=structured.get("page"),
            quote=structured.get("quote"),
        )
        return cls(
            id=value.get("id"),
            category=str(value.get("category") or "other"),
            content=str(value.get("content") or ""),
            source=source,
            confidence=float(value.get("confidence_score") or value.get("confidence") or 1.0),
            structured_data=structured,
        )

    def to_prompt_dict(
        self,
        *,
        content_limit: int | None = None,
        quote_limit: int | None = None,
    ) -> dict:
        content_limit = content_limit or settings.DRAFT_MAX_FACT_CHARS
        quote_limit = quote_limit or settings.DRAFT_MAX_FACT_QUOTE_CHARS
        return {
            "id": self.id,
            "category": self.category,
            "content": _truncate_text(self.content, content_limit),
            "confidence": self.confidence,
            "source": {
                "document_id": self.source.document_id,
                "document_name": self.source.document_name,
                "page": self.source.page,
                "quote": _truncate_text(self.source.quote, quote_limit),
            },
        }


@dataclass
class ArgumentUnit:
    key: str
    title: str
    legal_standard: str
    required_fact_categories: set[str]
    selected_facts: list[CaseFact] = field(default_factory=list)

    def to_prompt_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "legal_standard": self.legal_standard,
            "selected_fact_ids": [fact.id for fact in self.selected_facts if fact.id],
            "evidence": [fact.to_prompt_dict() for fact in self.selected_facts],
        }


@dataclass
class DraftPlan:
    case_type: str
    title: str
    arguments: list[ArgumentUnit]

    def to_prompt_dict(self) -> dict:
        return {
            "case_type": audit_case_type_label(self.case_type),
            "title": self.title,
            "arguments": [argument.to_prompt_dict() for argument in self.arguments],
        }


# ── Prompt templates ──────────────────────────────────────────────────────────

DRAFT_SYSTEM_PROMPT = """You are a senior audit document drafting assistant.
You draft the document type, language, tone, structure, and level of detail requested by the auditor.

Your writing must:
- Treat the auditor's title, instructions, and selected knowledge references as the controlling format requirements
- Use formal, objective audit language and distinguish observed facts, procedures, findings, and limitations
- Cite specific facts and quantitative evidence from the selected facts
- Connect facts to audit objectives or supplied standards only when the requested format calls for that analysis
- Preserve factual accuracy and avoid inventing evidence
- Be specific and concrete, never vague"""

DRAFT_PROMPT_TEMPLATE = """Draft a user-customized audit document for human review.
AUDIT TYPE BACKGROUND: {case_type}
Use the case type as background only; it does not determine the document format by itself.

DOCUMENT TITLE:
{draft_title_instruction}

AUDITOR'S REQUIRED FORMAT AND CONTENT INSTRUCTIONS:
{user_prompt_section}

AUDIT FACTS (use these as the factual record):
{facts_json}

{organization_context_section}
{knowledge_section}
SELECTED STRATEGY: {style_name}
STRATEGY GUIDANCE: {style_description}
FORMAT BOUNDARY:
{format_boundary}

OUTPUT RULES:
1. The auditor's instructions control the document type, section order, language, tone, and formatting. Do not default to any fixed legacy format unless the auditor asks for it.
2. Start with one visible Markdown title line using "# Title"
3. Produce one complete, continuous full draft in the requested format.
4. Treat any organization context as helper input, not mandatory section headings.
5. Do not impose a fixed audit report, opinion, salutation, or signature block unless the auditor's title or instructions explicitly request that format.
6. If the auditor specifies headings or sections, use those headings as the primary outline.
7. Use the strongest selected case facts and knowledge references to satisfy the requested requirements; summarize supporting facts instead of exhaustively repeating every detail.
8. Knowledge references are supporting material; do not copy their document type, boilerplate, or filing structure when it conflicts with the auditor's requested format.
9. Do not invent facts, source citations, dates, amounts, procedures, test results, or audit conclusions not supported by the record.
10. If the requested format includes audit findings, connect each finding to the supplied criterion, evidence, risk, and recommendation; state evidence gaps and do not assume a standard is satisfied.
11. If the requested format is a workpaper, memo, outline, management letter, evidence summary, audit query response, or other custom document, follow that format. Drafts and suggested findings require auditor approval; do not claim an audit opinion has been issued.
12. Target length: {target_length}, unless the auditor specified a different length.
13. Return only the final draft content. Do not include analysis, notes, or <think> blocks.

Draft the requested document now:"""


SECTION_REWRITE_PROMPT = """You are an experienced audit document drafting assistant. Rewrite the following full draft
according to the auditor's instruction while preserving cited evidence, factual limits, and only the findings that fit the requested format. Do not invent completed procedures or turn an unreviewed finding into an issued audit opinion.

ORIGINAL FULL DRAFT:
{original_content}

AUDITOR'S INSTRUCTION:
{instruction}

RELEVANT FACTS TO KEEP:
{facts_json}
{knowledge_section}
REWRITE STRATEGY: {style_description}
FORMAT BOUNDARY:
{format_boundary}

Rewrite the full draft now. Follow the auditor's requested format, structure, language, and tone. Return only the rewritten draft content."""


STRATEGY_STYLES = {
    "strongest_first": {
        "style_name": "strongest-evidence-first",
        "style_description": "Lead with the strongest evidence and facts. Weaker evidence may support the draft, but should not carry the core message.",
        "target_length": "1600-2200 words",
    },
    "conservative": {
        "style_name": "conservative analysis",
        "style_description": "Use a careful, formal, non-exaggerated tone. Cite sources clearly and avoid overclaiming weak evidence.",
        "target_length": "1500-2100 words",
    },
    "narrative": {
        "style_name": "audit narrative",
        "style_description": "Open with the audit objective or most significant supported finding, then organize the facts under the auditor's requested sections.",
        "target_length": "1400-2000 words",
    },
    "criterion": {
        "style_name": "section-by-section analysis",
        "style_description": "Use the auditor's requested sections as the organizing points. Do not add any section framework that the title or instructions did not request.",
        "target_length": "1600-2200 words",
    },
}


# The legacy names remain internal interfaces; their prompt vocabulary is audit-specific.
LEGAL_CONTEXT_KEYWORDS = (
    "audit criterion", "audit criteria", "criterion-by-criterion", "criteria analysis",
    "audit objective", "audit standard", "assertion", "compliance requirement",
    "control test", "audit finding", "audit query", "审计要件", "审计标准",
    "审计目标", "审计认定", "合规要求", "控制测试", "审计发现", "审计询证",
    "逐项分析", "逐项对应", "满足标准",
)

CASE_TYPE_LEGAL_MARKERS = (
    "financial audit", "internal audit", "compliance audit", "operational audit",
    "it audit", "special audit", "财务审计", "内部审计", "合规审计", "运营审计",
    "信息技术审计", "专项审计",
)

NEGATED_LEGAL_CONTEXT_PHRASES = (
    "do not use audit criteria", "do not organize by audit criteria",
    "only map to audit criteria when explicitly requested", "audit criteria when explicitly requested",
    "no audit criteria", "no criteria analysis", "不要按审计要件", "不要审计要件",
    "不需要审计要件", "不需要审计认定分析", "只有明确要求审计要件时才对应审计标准",
    "只有在明确要求审计要件时才对应审计标准",
)

def _normalized_text(*values: str | None) -> str:
    return "\n".join(value for value in values if value).lower()


def _strip_negated_legal_phrases(text: str) -> str:
    cleaned = text
    for phrase in NEGATED_LEGAL_CONTEXT_PHRASES:
        cleaned = cleaned.replace(phrase.lower(), " ")
    return cleaned


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def requests_legal_criteria_context(
    *,
    draft_title: str = "",
    user_prompt: str = "",
    criteria: Optional[list[str]] = None,
) -> bool:
    """Return True only when the auditor explicitly asks for audit objectives/criteria analysis."""
    if criteria:
        return True

    raw_text = _normalized_text(draft_title, user_prompt)
    if not raw_text.strip():
        return False

    text = _strip_negated_legal_phrases(raw_text)
    if _contains_any(text, LEGAL_CONTEXT_KEYWORDS):
        return True

    has_case_type_marker = _contains_any(text, CASE_TYPE_LEGAL_MARKERS)
    has_argument_marker = _contains_any(
        text,
        (
            "analysis",
            "argument",
            "brief",
            "memo",
            "evidence memo",
            "standard",
            "论证",
            "分析",
            "备忘录",
            "标准",
            "要件",
        ),
    )
    return has_case_type_marker and has_argument_marker


def build_knowledge_section(
    knowledge_refs: Optional[list[dict]],
    *,
    legal_context_required: bool = False,
) -> str:
    if not knowledge_refs:
        return ""
    knowledge_parts = []
    for ki in knowledge_refs[: settings.DRAFT_MAX_KNOWLEDGE_ITEMS]:
        ref_type = ki.get("type", "reference")
        guidance = "Use as prior draft/history context only when it fits the auditor's current requested format; update facts and strategy."
        if ref_type != "draft_history":
            guidance = "Use as style, structure, template, sample, or agent-strategy guidance. If it conflicts with the auditor's instructions, the auditor's instructions control."
        if not legal_context_required:
            guidance += " Do not copy a report opinion, boilerplate, salutation, or signature block unless the current instructions request it. Audit objectives here are generic organizing aids; use applicable standards only when supplied in the current evidence or references."
        content = _truncate_text(str(ki.get("content") or ""), settings.DRAFT_MAX_KNOWLEDGE_CHARS)
        knowledge_parts.append(f"--- {ki['title']} ({ref_type}) ---\n{guidance}\n{content}")
    return "\nKNOWLEDGE BASE AND DRAFT HISTORY REFERENCES:\n" + "\n\n".join(knowledge_parts) + "\n"


def _criteria_map_for_case(case_type: str, criteria: Optional[list[str]] = None) -> dict[str, str]:
    criteria_map = EB1A_CRITERIA if case_type in ("EB1A", "EB1B", "O1A") else NIW_CRITERIA
    if criteria:
        criteria_map = {k: v for k, v in criteria_map.items() if k in criteria}
    return criteria_map


def _limit_draft_plan(plan: DraftPlan, max_facts: int) -> DraftPlan:
    remaining = max(max_facts, 0)
    limited_arguments: list[ArgumentUnit] = []
    for argument in plan.arguments:
        if remaining <= 0:
            break
        argument.selected_facts = argument.selected_facts[:remaining]
        remaining -= len(argument.selected_facts)
        if argument.selected_facts:
            limited_arguments.append(argument)
    plan.arguments = limited_arguments
    return plan


def _format_boundary(legal_context_required: bool) -> str:
    if legal_context_required:
        return (
            "The auditor requested audit objectives, findings, queries, or criteria-based organization. "
            "Use audit objectives as organizing aids and cite only applicable standards supplied in the evidence or references."
        )
    return (
        "The auditor did not request criteria-based audit analysis. "
        "Do not impose audit criteria, standards, or default Criterion / Evidence / Finding headings. "
        "Follow the requested title, sections, facts, strategy, and selected knowledge references instead."
    )


class DraftGenerationAgent:
    def __init__(self, llm: Optional[LLMService] = None):
        self.llm = llm or LLMService()

    async def generate_draft(
        self,
        facts: list[dict],
        case_type: str = "EB1A",
        criteria: Optional[list[str]] = None,
        draft_title: str = "",
        user_prompt: str = "",
        strategy: str = "strongest_first",
        knowledge_refs: Optional[list[dict]] = None,
    ) -> str:
        """
        Generate one full draft from approved facts.
        Incorporates auditor strategy, user prompt, and knowledge base references.
        """
        legal_context_required = requests_legal_criteria_context(
            draft_title=draft_title,
            user_prompt=user_prompt,
            criteria=criteria,
        )
        orchestrator = DraftGenerationOrchestrator(
            facts=facts,
            case_type=case_type,
            criteria=criteria,
            draft_title=draft_title,
        )

        if legal_context_required:
            draft_plan = orchestrator.build_plan()
            draft_plan = _limit_draft_plan(draft_plan, settings.DRAFT_MAX_FACTS)
            selected_facts = orchestrator.selected_facts()
            selected_facts = selected_facts[: settings.DRAFT_MAX_FACTS]
            criteria_str = "\n".join(f"- {k}: {v}" for k, v in _criteria_map_for_case(case_type, criteria).items())
            draft_plan_json = json.dumps(draft_plan.to_prompt_dict(), ensure_ascii=False, indent=2)
            organization_context_section = (
                "AUDIT ANALYSIS CONTEXT (included because the auditor requested audit objectives, findings, queries, or criteria-based analysis):\n"
                "CROSS-DOCUMENT EVIDENCE ORGANIZATION:\n"
                f"{draft_plan_json}\n\n"
                "RELEVANT AUDIT OBJECTIVES:\n"
                f"{criteria_str}"
            )
        else:
            selected_facts = orchestrator.facts_for_custom_draft(limit=settings.DRAFT_MAX_FACTS)
            organization_context_section = (
                "CUSTOM DOCUMENT ORGANIZATION:\n"
                "No audit criteria context was injected because the auditor did not request criteria-based analysis. "
                "Use the facts directly under the auditor's requested headings and document type."
            )

        facts_json = json.dumps([fact.to_prompt_dict() for fact in selected_facts], ensure_ascii=False, indent=2)
        clean_draft_title = draft_title.strip()
        draft_title_instruction = (
            f'Use exactly this title: "{clean_draft_title}"'
            if clean_draft_title
            else "Generate a concise title that matches the requested document format."
        )

        user_prompt_section = (
            _truncate_text(user_prompt, settings.DRAFT_MAX_USER_PROMPT_CHARS)
            or "No additional custom instructions were provided. Create a clear full draft using the selected strategy, facts, and knowledge references."
        )

        knowledge_section = build_knowledge_section(
            knowledge_refs,
            legal_context_required=legal_context_required,
        )
        style = dict(STRATEGY_STYLES.get(strategy, STRATEGY_STYLES["strongest_first"]))
        if not legal_context_required:
            style["target_length"] = "match the requested format; if no length is specified, 700-1200 words"

        max_tokens = settings.DRAFT_GENERATION_MAX_TOKENS if legal_context_required else settings.DRAFT_CUSTOM_MAX_TOKENS
        logger.info(
            "Generating main draft strategy=%s legal_context=%s facts=%s knowledge_refs=%s max_tokens=%s",
            strategy,
            legal_context_required,
            len(selected_facts),
            len(knowledge_refs or []),
            max_tokens,
        )
        prompt = DRAFT_PROMPT_TEMPLATE.format(
            case_type=audit_case_type_label(case_type),
            draft_title_instruction=draft_title_instruction,
            facts_json=facts_json,
            organization_context_section=organization_context_section,
            user_prompt_section=user_prompt_section,
            knowledge_section=knowledge_section,
            format_boundary=_format_boundary(legal_context_required),
            **style,
        )
        return await self.llm.generate(
            prompt,
            system=DRAFT_SYSTEM_PROMPT,
            temperature=0.4,
            max_tokens=max_tokens,
        )

    async def generate_three_versions(
        self,
        facts: list[dict],
        case_type: str = "EB1A",
        criteria: Optional[list[str]] = None,
        draft_title: str = "",
        user_prompt: str = "",
        knowledge_refs: Optional[list[dict]] = None,
    ) -> dict[str, str]:
        """
        Backward-compatible wrapper. New product flow generates one main draft.
        """
        try:
            content = await self.generate_draft(
                facts=facts,
                case_type=case_type,
                criteria=criteria,
                draft_title=draft_title,
                user_prompt=user_prompt,
                strategy="strongest_first",
                knowledge_refs=knowledge_refs,
            )
        except Exception as e:
            logger.error(f"Main draft generation failed: {e}")
            content = f"[Generation failed: {e}]"
        return {"main": content}

    async def rewrite_section(
        self,
        original_content: str,
        instruction: str,
        relevant_facts: list[dict],
        strategy: str = "strongest_first",
        knowledge_refs: Optional[list[dict]] = None,
    ) -> str:
        """Rewrite a full draft based on auditor instruction."""
        legal_context_required = requests_legal_criteria_context(user_prompt=instruction)
        style = STRATEGY_STYLES.get(strategy, STRATEGY_STYLES["strongest_first"])
        compact_facts = [
            CaseFact.from_dict(fact).to_prompt_dict()
            for fact in relevant_facts[: settings.DRAFT_MAX_FACTS]
            if fact.get("content")
        ]
        prompt = SECTION_REWRITE_PROMPT.format(
            original_content=_truncate_text(original_content, 12000),
            instruction=_truncate_text(instruction, settings.DRAFT_MAX_USER_PROMPT_CHARS),
            facts_json=json.dumps(compact_facts, ensure_ascii=False, indent=2),
            knowledge_section=build_knowledge_section(
                knowledge_refs,
                legal_context_required=legal_context_required,
            ),
            style_description=style["style_description"],
            format_boundary=_format_boundary(legal_context_required),
        )
        return await self.llm.generate(
            prompt,
            system=DRAFT_SYSTEM_PROMPT,
            temperature=0.35,
            max_tokens=settings.DRAFT_REWRITE_MAX_TOKENS,
        )

    async def generate_rfi_response(
        self,
        rfi_text: str,
        case_facts: list[dict],
        additional_docs: list[str],
    ) -> str:
        """Generate an audit information or evidence request response."""
        system = "You are an experienced audit assistant responding to an audit information or evidence request. Address each point, cite available evidence precisely, identify missing evidence, and require auditor review before issue."
        prompt = f"""Write a professional response to the following audit information request:

AUDIT QUERY TEXT:
{rfi_text}

AVAILABLE EVIDENCE:
{json.dumps(case_facts, ensure_ascii=False, indent=2)}

ADDITIONAL SUBMITTED DOCUMENTS:
{chr(10).join(f'- {d}' for d in additional_docs)}

Write an objective, evidence-supported draft audit query response. Distinguish confirmed evidence from items still requiring follow-up:"""
        return await self.llm.generate(prompt, system=system, temperature=0.3, max_tokens=4096)


class DraftGenerationOrchestrator:
    """
    Internal scheduling layer for draft generation.

    Uploaded documents are normalized into case-level facts first. The orchestrator then
    plans audit evidence themes and selects evidence across every uploaded material before the
    final full-draft prompt is composed.
    """

    def __init__(
        self,
        facts: list[dict],
        case_type: str,
        criteria: Optional[list[str]] = None,
        draft_title: str = "",
    ):
        self.case_type = case_type
        self.criteria = criteria
        self.draft_title = draft_title.strip()
        self.facts = [CaseFact.from_dict(fact) for fact in facts if fact.get("content")]

    def build_plan(self) -> DraftPlan:
        criteria_map = EB1A_CRITERIA if self.case_type in ("EB1A", "EB1B", "O1A") else NIW_CRITERIA
        category_map = CRITERION_FACT_CATEGORIES if self.case_type in ("EB1A", "EB1B", "O1A") else NIW_FACT_CATEGORIES
        if self.criteria:
            criteria_map = {key: value for key, value in criteria_map.items() if key in self.criteria}

        arguments: list[ArgumentUnit] = []
        for key, standard in criteria_map.items():
            unit = ArgumentUnit(
                key=key,
                title=self._argument_title(key, standard),
                legal_standard=standard,
                required_fact_categories=category_map.get(key, {"evidence", "other"}),
            )
            unit.selected_facts = self.select_facts_for_argument(unit)
            if unit.selected_facts:
                arguments.append(unit)

        if not arguments:
            fallback = ArgumentUnit(
                key="case_merits",
                title="Overall Audit Evidence and Findings",
                legal_standard="Use available evidence to describe findings and limitations without assuming a completed audit conclusion.",
                required_fact_categories={fact.category for fact in self.facts} or {"other"},
                selected_facts=self._rank_facts(self.facts)[:18],
            )
            arguments.append(fallback)

        return DraftPlan(
            case_type=self.case_type,
            title=self.draft_title or "Custom Draft",
            arguments=arguments,
        )

    def selected_facts(self) -> list[CaseFact]:
        seen: set[str] = set()
        selected: list[CaseFact] = []
        for argument in self.build_plan().arguments:
            for fact in argument.selected_facts:
                identity = fact.id or fact.content
                if identity in seen:
                    continue
                seen.add(identity)
                selected.append(fact)
        return selected or self._rank_facts(self.facts)[:30]

    def facts_for_custom_draft(self, limit: int = 40) -> list[CaseFact]:
        return self._rank_facts(self._dedupe_facts(self.facts))[:limit]

    def select_facts_for_argument(self, argument: ArgumentUnit, limit: int = 12) -> list[CaseFact]:
        category_matches = [
            fact for fact in self.facts
            if self._normalized_category(fact.category) in argument.required_fact_categories
        ]
        semantic_matches = [
            fact for fact in self.facts
            if self._matches_argument_text(fact, argument)
        ]
        combined = self._dedupe_facts(category_matches + semantic_matches)
        return self._rank_facts(combined)[:limit]

    def _argument_title(self, key: str, standard: str) -> str:
        if key.startswith("criterion_"):
            return f"{key.replace('_', ' ').title()}: {standard}"
        return standard

    def _matches_argument_text(self, fact: CaseFact, argument: ArgumentUnit) -> bool:
        haystack = f"{fact.category} {fact.content}".lower()
        keywords = {
            token.strip(".,;:()[]{}").lower()
            for token in f"{argument.title} {argument.legal_standard}".split()
            if len(token.strip(".,;:()[]{}")) >= 5
        }
        return sum(1 for token in keywords if token in haystack) >= 2

    def _rank_facts(self, facts: list[CaseFact]) -> list[CaseFact]:
        def score(fact: CaseFact) -> tuple[float, int, int]:
            source_bonus = 1 if fact.source.document_name or fact.source.quote else 0
            specificity = min(len(fact.content), 600)
            return (fact.confidence, source_bonus, specificity)

        return sorted(facts, key=score, reverse=True)

    def _dedupe_facts(self, facts: list[CaseFact]) -> list[CaseFact]:
        seen: set[str] = set()
        unique: list[CaseFact] = []
        for fact in facts:
            identity = fact.id or fact.content.strip().lower()
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(fact)
        return unique

    def _normalized_category(self, category: str) -> str:
        value = category.lower().strip()
        aliases = {
            "reference": "reference_letter",
            "letter": "reference_letter",
            "peer review": "peer_review",
            "judging": "judge",
        }
        return aliases.get(value, value)
