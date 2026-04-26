"""
Draft Generation Agent

Generates one strategy-driven, lawyer-customized immigration case document
from selected case facts and knowledge references.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.llm.provider import LLMService

logger = logging.getLogger(__name__)


# ── EB-1A Criterion definitions ───────────────────────────────────────────────

EB1A_CRITERIA = {
    "criterion_1":  "Receipt of lesser nationally or internationally recognized prizes or awards for excellence",
    "criterion_2":  "Membership in associations requiring outstanding achievement",
    "criterion_3":  "Published material about the alien in professional or major trade publications",
    "criterion_4":  "Participation as a judge of others' work",
    "criterion_5":  "Original scientific, scholarly, artistic, athletic, or business-related contributions of major significance",
    "criterion_6":  "Authorship of scholarly articles in professional journals or major media",
    "criterion_7":  "Display of work at artistic exhibitions or showcases",
    "criterion_8":  "Performance in a leading or critical role for organizations with distinguished reputations",
    "criterion_9":  "High salary or remuneration commanding in comparison to others in the field",
    "criterion_10": "Commercial successes in the performing arts",
}

NIW_CRITERIA = {
    "criterion_1": "The proposed endeavor has substantial merit and national importance",
    "criterion_2": "The applicant is well-positioned to advance the proposed endeavor",
    "criterion_3": "On balance, it would be beneficial to the United States to waive the job offer requirement",
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

    def to_prompt_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "content": self.content,
            "confidence": self.confidence,
            "source": {
                "document_id": self.source.document_id,
                "document_name": self.source.document_name,
                "page": self.source.page,
                "quote": self.source.quote,
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
            "case_type": self.case_type,
            "title": self.title,
            "arguments": [argument.to_prompt_dict() for argument in self.arguments],
        }


# ── Prompt templates ──────────────────────────────────────────────────────────

DRAFT_SYSTEM_PROMPT = """You are a senior immigration case-document drafting assistant with 20+ years of experience.
You draft the document type, language, tone, structure, and level of detail requested by the lawyer.

Your writing must:
- Treat the lawyer's title, instructions, and selected knowledge references as the controlling format requirements
- Use formal legal language when the requested output is a legal submission or attorney work product
- Cite specific facts and quantitative evidence from the selected facts
- Connect facts to immigration criteria only when the requested format calls for legal argument
- Preserve factual accuracy and avoid inventing evidence
- Be specific and concrete, never vague"""

DRAFT_PROMPT_TEMPLATE = """Draft a user-customized immigration case document.
CASE TYPE BACKGROUND: {case_type}
Use the case type as background only; it does not determine the document format by itself.

DOCUMENT TITLE:
{draft_title_instruction}

LAWYER'S REQUIRED FORMAT AND CONTENT INSTRUCTIONS:
{user_prompt_section}

CASE FACTS (use these as the factual record):
{facts_json}

{organization_context_section}
{knowledge_section}
SELECTED STRATEGY: {style_name}
STRATEGY GUIDANCE: {style_description}
FORMAT BOUNDARY:
{format_boundary}

OUTPUT RULES:
1. The lawyer's instructions control the document type, section order, language, tone, and formatting. Do not default to any fixed legacy format unless the lawyer asks for it.
2. Start with one visible Markdown title line using "# Title"
3. Produce one complete, continuous full draft in the requested format.
4. Treat any organization context as helper input, not mandatory section headings.
5. Do not use a USCIS filing-letter structure, salutation, signature block, or fixed eligibility brief structure unless the lawyer's title or instructions explicitly request that kind of filing draft.
6. If the lawyer specifies headings or sections, use those headings as the primary outline.
7. Use the selected case facts and knowledge references to satisfy the requested requirements.
8. Knowledge references are supporting material; do not copy their document type, boilerplate, or filing structure when it conflicts with the lawyer's requested format.
9. Do not invent facts, citations, dates, awards, roles, publications, or legal conclusions not supported by the record.
10. If the requested format includes immigration eligibility arguments, connect facts to the relevant legal criteria and explain why the standards are met.
11. If the requested format is a memo, outline, client letter, evidence summary, strategy note, RFE response, or other custom document, follow that format instead of a fixed filing structure.
12. Target length: {target_length}, unless the lawyer specified a different length.
13. Return only the final draft content. Do not include analysis, notes, or <think> blocks.

Draft the requested document now:"""


SECTION_REWRITE_PROMPT = """You are an experienced immigration case-document drafting assistant. Rewrite the following full draft
according to the lawyer's instruction while preserving cited facts and only the legal arguments that still fit the requested format.

ORIGINAL FULL DRAFT:
{original_content}

LAWYER'S INSTRUCTION:
{instruction}

RELEVANT FACTS TO KEEP:
{facts_json}
{knowledge_section}
REWRITE STRATEGY: {style_description}
FORMAT BOUNDARY:
{format_boundary}

Rewrite the full draft now. Follow the lawyer's requested format, structure, language, and tone. Return only the rewritten draft content."""


STRATEGY_STYLES = {
    "strongest_first": {
        "style_name": "strongest-evidence-first",
        "style_description": "Lead with the strongest evidence and facts. Weaker evidence may support the draft, but should not carry the core message.",
        "target_length": "2500-3500 words",
    },
    "conservative": {
        "style_name": "conservative analysis",
        "style_description": "Use a careful, formal, non-exaggerated tone. Cite sources clearly and avoid overclaiming weak evidence.",
        "target_length": "2200-3200 words",
    },
    "narrative": {
        "style_name": "narrative persuasion",
        "style_description": "Open with the beneficiary's core contribution or strongest theme, then organize the facts under the lawyer's requested sections.",
        "target_length": "2000-2800 words",
    },
    "criterion": {
        "style_name": "section-by-section analysis",
        "style_description": "Use the lawyer's requested sections as the organizing points. Do not add any section framework that the title or instructions did not request.",
        "target_length": "2500-3500 words",
    },
}


LEGAL_CONTEXT_KEYWORDS = (
    "legal criterion",
    "legal criteria",
    "criterion-by-criterion",
    "criteria analysis",
    "eligibility",
    "legal standard",
    "regulatory",
    "8 c.f.r",
    "uscis",
    "rfe",
    "rfi",
    "request for evidence",
    "notice of intent",
    "noid",
    "i-140",
    "filing draft",
    "filing letter",
    "submission letter",
    "extraordinary ability",
    "national interest waiver",
    "dhanasar",
    "petition",
    "法律要件",
    "法定要件",
    "法律标准",
    "法定标准",
    "法规",
    "移民局",
    "补件",
    "rfe",
    "rfi",
    "noid",
    "递交",
    "资格论证",
    "资格分析",
    "证据论证",
    "法律论证",
    "要件论证",
    "逐项论证",
    "逐项对应",
    "满足标准",
    "申请信",
    "申请书",
    "请愿",
)

CASE_TYPE_LEGAL_MARKERS = (
    "eb1a",
    "eb-1a",
    "eb1b",
    "eb-1b",
    "niw",
    "o1a",
    "o-1a",
)

NEGATED_LEGAL_CONTEXT_PHRASES = (
    "do not write a petition",
    "do not write petition",
    "do not use a filing-letter structure",
    "do not use legal criteria",
    "do not organize by legal criteria",
    "only map to legal criteria when explicitly requested",
    "legal criteria when explicitly requested",
    "no legal criteria",
    "no eligibility analysis",
    "不要写申请信",
    "不要写申请书",
    "不要写请愿",
    "不要请愿",
    "不要按法律要件",
    "不要法律要件",
    "不要法定要件",
    "不需要法律要件",
    "不需要资格论证",
    "不要资格论证",
    "不要法律论证",
    "只有明确要求法律要件时才对应法定标准",
    "只有在明确要求法律要件时才对应法定标准",
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
    """Return True only when the lawyer explicitly asks for filing/criteria analysis."""
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
    for ki in knowledge_refs:
        ref_type = ki.get("type", "reference")
        guidance = "Use as prior draft/history context only when it fits the lawyer's current requested format; update facts and strategy."
        if ref_type != "draft_history":
            guidance = "Use as style, structure, template, sample, or agent-strategy guidance. If it conflicts with the lawyer's instructions, the lawyer's instructions control."
        if not legal_context_required:
            guidance += " Do not copy USCIS filing, eligibility-brief, salutation, or signature-block structure unless the current instructions request it."
        knowledge_parts.append(f"--- {ki['title']} ({ref_type}) ---\n{guidance}\n{ki['content'][:2000]}")
    return "\nKNOWLEDGE BASE AND DRAFT HISTORY REFERENCES:\n" + "\n\n".join(knowledge_parts) + "\n"


def _criteria_map_for_case(case_type: str, criteria: Optional[list[str]] = None) -> dict[str, str]:
    criteria_map = EB1A_CRITERIA if case_type in ("EB1A", "EB1B", "O1A") else NIW_CRITERIA
    if criteria:
        criteria_map = {k: v for k, v in criteria_map.items() if k in criteria}
    return criteria_map


def _format_boundary(legal_context_required: bool) -> str:
    if legal_context_required:
        return (
            "The lawyer requested legal, eligibility, USCIS/RFE, or criteria-based organization. "
            "Use legal standards only where they support the requested document type."
        )
    return (
        "The lawyer did not request eligibility analysis or filing-style argument. "
        "Do not organize by USCIS criteria, regulatory standards, or default Legal Standard / Evidence / Analysis headings. "
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
        Incorporates lawyer strategy, user prompt, and knowledge base references.
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
            selected_facts = orchestrator.selected_facts()
            criteria_str = "\n".join(f"- {k}: {v}" for k, v in _criteria_map_for_case(case_type, criteria).items())
            draft_plan_json = json.dumps(draft_plan.to_prompt_dict(), ensure_ascii=False, indent=2)
            organization_context_section = (
                "LEGAL ARGUMENT CONTEXT (included because the lawyer requested filing, eligibility, RFE, or criteria-based analysis):\n"
                "CROSS-DOCUMENT EVIDENCE ORGANIZATION:\n"
                f"{draft_plan_json}\n\n"
                "RELEVANT LEGAL CRITERIA:\n"
                f"{criteria_str}"
            )
        else:
            selected_facts = orchestrator.facts_for_custom_draft()
            organization_context_section = (
                "CUSTOM DOCUMENT ORGANIZATION:\n"
                "No legal criteria context was injected because the lawyer did not request eligibility analysis or filing-style argument. "
                "Use the facts directly under the lawyer's requested headings and document type."
            )

        facts_json = json.dumps([fact.to_prompt_dict() for fact in selected_facts], ensure_ascii=False, indent=2)
        clean_draft_title = draft_title.strip()
        draft_title_instruction = (
            f'Use exactly this title: "{clean_draft_title}"'
            if clean_draft_title
            else "Generate a concise title that matches the requested document format."
        )

        user_prompt_section = (
            user_prompt.strip()
            or "No additional custom instructions were provided. Create a clear full draft using the selected strategy, facts, and knowledge references."
        )

        knowledge_section = build_knowledge_section(
            knowledge_refs,
            legal_context_required=legal_context_required,
        )
        style = dict(STRATEGY_STYLES.get(strategy, STRATEGY_STYLES["strongest_first"]))
        if not legal_context_required:
            style["target_length"] = "match the requested format; if no length is specified, 900-1600 words"

        logger.info(f"Generating main draft with strategy={strategy}...")
        prompt = DRAFT_PROMPT_TEMPLATE.format(
            case_type=case_type,
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
            max_tokens=4096,
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
        """Rewrite a full draft based on lawyer instruction."""
        legal_context_required = requests_legal_criteria_context(user_prompt=instruction)
        style = STRATEGY_STYLES.get(strategy, STRATEGY_STYLES["strongest_first"])
        prompt = SECTION_REWRITE_PROMPT.format(
            original_content=original_content,
            instruction=instruction,
            facts_json=json.dumps(relevant_facts, ensure_ascii=False, indent=2),
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
            max_tokens=2048,
        )

    async def generate_rfi_response(
        self,
        rfi_text: str,
        case_facts: list[dict],
        additional_docs: list[str],
    ) -> str:
        """Generate a response to a USCIS Request for Evidence (RFI/RFE)."""
        system = "You are an experienced immigration attorney responding to a USCIS Request for Evidence. Be thorough, cite evidence precisely, and address every point raised."
        prompt = f"""Write a professional response to the following USCIS RFE/RFI:

RFE/RFI TEXT:
{rfi_text}

AVAILABLE EVIDENCE:
{json.dumps(case_facts, ensure_ascii=False, indent=2)}

ADDITIONAL SUBMITTED DOCUMENTS:
{chr(10).join(f'- {d}' for d in additional_docs)}

Write a complete, legally sound RFE response letter body:"""
        return await self.llm.generate(prompt, system=system, temperature=0.3, max_tokens=4096)


class DraftGenerationOrchestrator:
    """
    Internal scheduling layer for draft generation.

    Uploaded documents are normalized into case-level facts first. The orchestrator then
    plans legal arguments and selects evidence across every uploaded material before the
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
                title="Overall Eligibility and Merits",
                legal_standard="Use the strongest available evidence to establish eligibility.",
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
