"""
Fact Extraction Agent

Pipeline:
  1. Parse raw document (PDF / Word / image) → plain text
  2. Ask LLM to extract structured facts (JSON)
  3. Save facts to DB, update document parse_status
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.config import settings
from app.llm.provider import LLMService, strip_think_tags

logger = logging.getLogger(__name__)


class DocumentTextExtractionError(RuntimeError):
    """Raised when an uploaded document has no usable text for fact extraction."""


# ── Document text extraction ──────────────────────────────────────────────────

def extract_text_from_file(file_path: str, mime_type: str = "", max_chars: Optional[int] = None) -> str:
    """Extract plain text from PDF, Word, or image file."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf" or "pdf" in mime_type:
        return _extract_pdf(file_path, max_chars=max_chars)
    elif suffix in (".docx", ".doc") or "word" in mime_type:
        return _extract_docx(file_path)
    elif suffix in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        return _extract_image_ocr(file_path)
    elif suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    else:
        # Fallback: try PDF then plain text
        try:
            return _extract_pdf(file_path, max_chars=max_chars)
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore")


def _extract_pdf(file_path: str, max_chars: Optional[int] = None) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        try:
            embedded_text = _extract_pdf_embedded_text(doc, max_chars=max_chars)
            if len(embedded_text.strip()) >= settings.PARSE_MIN_READABLE_TEXT_CHARS:
                return embedded_text

            ocr_text = _extract_pdf_ocr(doc, max_chars=max_chars)
            return ocr_text or embedded_text
        finally:
            doc.close()
    except ImportError:
        logger.warning("PyMuPDF not installed, falling back to plain read")
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")


def _extract_pdf_embedded_text(doc, max_chars: Optional[int] = None) -> str:
    if not max_chars or len(doc) <= 8:
        return "\n\n".join(page.get_text("text") for page in doc)

    head_limit = max(1, int(max_chars * 0.7))
    tail_limit = max(1, max_chars - head_limit)
    head_pages: list[str] = []
    tail_pages: list[str] = []
    head_chars = 0
    tail_chars = 0
    head_end = 0

    for page_index in range(len(doc)):
        text = doc[page_index].get_text("text")
        head_pages.append(text)
        head_chars += len(text)
        head_end = page_index + 1
        if head_chars >= head_limit:
            break

    for page_index in range(len(doc) - 1, head_end - 1, -1):
        text = doc[page_index].get_text("text")
        tail_pages.append(text)
        tail_chars += len(text)
        if tail_chars >= tail_limit:
            break

    if tail_pages:
        omitted = max(0, len(doc) - head_end - len(tail_pages))
        return "\n\n".join(head_pages) + f"\n\n[... {omitted} middle PDF pages omitted ...]\n\n" + "\n\n".join(reversed(tail_pages))
    return "\n\n".join(head_pages)


def _extract_pdf_ocr(doc, max_chars: Optional[int] = None) -> str:
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning("PDF OCR dependencies not installed")
        return ""

    page_limit = min(len(doc), max(1, int(settings.PARSE_PDF_OCR_MAX_PAGES or 1)))
    scale = max(1.0, float(settings.PARSE_PDF_OCR_DPI or 180) / 72.0)
    matrix = fitz.Matrix(scale, scale)
    chunks: list[str] = []
    chars = 0

    for page_index in range(page_limit):
        try:
            page = doc[page_index]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
        except Exception as exc:
            logger.warning("PDF OCR failed on page %s: %s", page_index + 1, str(exc)[:200])
            continue

        if not text:
            continue
        chunk = f"[OCR page {page_index + 1}]\n{text}"
        chunks.append(chunk)
        chars += len(chunk)
        if max_chars and chars >= max_chars:
            break

    extracted = "\n\n".join(chunks)
    if max_chars and len(extracted) > max_chars:
        return extracted[:max_chars].rstrip()
    return extracted


def _extract_docx(file_path: str) -> str:
    try:
        from docx import Document
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        logger.warning("python-docx not installed")
        return ""


def _extract_image_ocr(file_path: str) -> str:
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(file_path)
        return pytesseract.image_to_string(img, lang="chi_sim+eng")
    except ImportError:
        logger.warning("pytesseract/Pillow not installed")
        return ""
    except Exception as exc:
        logger.warning("Image OCR failed: %s", str(exc)[:200])
        return ""


# ── Fact extraction via LLM ───────────────────────────────────────────────────

FACT_EXTRACTION_SYSTEM = """You are an expert immigration lawyer assistant specializing in EB-1A, EB-1B, NIW, and O-1A petitions.
Extract verifiable, evidence-backed facts from the provided document. Prefer concise facts that a lawyer can verify and use.
For resumes, CVs, biographies, personal profiles, and custom evidence packets, do not discard objective background entries merely because they look like résumé history.
Classify each fact into one of: award, original_contribution, patent, publication, citation, employment, media, membership, education, salary, reference_letter, other.
Return ONLY a valid JSON array — no markdown, no explanation."""

DOC_TYPE_GUIDANCE = {
    "award": "Focus on award name, level, granting organization, selection criteria, date, competitiveness, and field recognition.",
    "original_contribution": "Focus on the original contribution, novelty, adoption/use, measurable impact, citations, patents/products, independent validation, and field significance.",
    "patent": "Focus on patent title, number, inventors, jurisdiction, filing/grant dates, claims, commercialization, adoption, and technical impact.",
    "publication": "Focus on publication title, venue, date, authorship role, journal/conference standing, citations, and scholarly impact.",
    "citation": "Focus on citation counts, citing sources, benchmark comparisons, and evidence that others rely on the work.",
    "employment": "Focus on role, employer reputation, dates, critical duties, leadership, business/technical outcomes, and measurable impact.",
    "media": "Focus on outlet name, publication date, audience/reputation, subject of coverage, and why the coverage indicates recognition.",
    "membership": "Focus on organization, membership criteria, selection evidence, date, and whether outstanding achievement is required.",
    "reference_letter": "Focus on the recommender identity, basis of knowledge, independent validation, specific claims, and cited evidence.",
    "resume": "Treat this as a resume/CV/profile, not as a narrative petition exhibit. Extract every objective, verifiable career fact: education, degrees, employers, roles, dates, leadership, publications, patents, awards, memberships, peer review, invited talks, projects, metrics, and impact. One fact per distinct resume entry; do not merge the whole resume into a summary and do not discard background history.",
    "cv": "Treat this as a resume/CV/profile, not as a narrative petition exhibit. Extract every objective, verifiable career fact: education, degrees, employers, roles, dates, leadership, publications, patents, awards, memberships, peer review, invited talks, projects, metrics, and impact. One fact per distinct resume entry; do not merge the whole resume into a summary and do not discard background history.",
    "rfi": "Focus on every USCIS concern, requested evidence, deadlines, and response themes.",
}

CUSTOM_DOC_TYPE_GUIDANCE = (
    "Treat this as a user-defined evidence packet. Extract all objective facts that can be verified from the file, "
    "including resume/CV-style background, education, roles, publications, awards, memberships, projects, dates, names, numbers, and source-backed impact. "
    "Do not reject verifiable background details simply because they are not already framed as legal arguments."
)

FACT_EXTRACTION_PROMPT_TEMPLATE = """Extract structured facts from the following document for an immigration petition.

Extraction mode: high recall. The first pass should preserve potentially useful objective facts; do not make final legal-value decisions yet.
Document type hint: {doc_type}
Document name: {document_name}
Content scope: {content_scope}
Global extraction budget: at most {global_max_facts} facts for the whole document.
Document-specific extraction guidance: {doc_type_guidance}
Case type: {case_type}
Lawyer guidance:
{lawyer_guidance}
{resume_inventory}

--- Document Content ---
{content}
--- End ---

Return a JSON array of facts. Each fact object must have:
{{
  "category": "<award|original_contribution|patent|publication|citation|employment|media|membership|education|salary|reference_letter|other>",
  "content": "<1-3 sentence human-readable summary of the fact>",
  "structured_data": {{
    "title": "...",
    "date": "YYYY-MM-DD or year only",
    "organization": "...",
    "impact": "...",
    "numbers": "any quantitative data",
    "source": "document section or quote"
  }},
  "confidence_score": 0.0-1.0
}}

Extract at most {max_facts} useful facts from this content scope. Avoid duplicates and unsupported claims. For resumes/CVs/profiles/custom types, objective background entries are useful facts when they include names, dates, roles, organizations, outputs, or metrics.
Use structured_data.review_status = "candidate" for high-recall facts that should be lawyer-reviewed. Use structured_data.source with the section, heading, page marker, or short quote whenever possible.
Output JSON array only."""

FACT_EXTRACTION_FALLBACK_PROMPT_TEMPLATE = """The previous extraction returned no facts. Retry with a broader extraction scope for an immigration lawyer.

Document type hint: {doc_type}
Document name: {document_name}
Content scope: {content_scope}
Global extraction budget: at most {global_max_facts} facts for the whole document.
Document-specific extraction guidance: {doc_type_guidance}
Case type: {case_type}
Lawyer guidance:
{lawyer_guidance}
{resume_inventory}

Important retry rules:
- Return facts even when the document is a resume, CV, biography, profile, certificate, letter, or custom evidence packet.
- Extract objective entries such as education, employment, roles, dates, awards, publications, patents, memberships, service, reviews, projects, metrics, and named organizations.
- One fact per distinct entry is acceptable.
- For resumes/CVs, do not output one general career summary. Split entries into separate facts and preserve dates, organizations, titles, venues, numbers, and source section names.
- Do not invent missing information; use "other" when the category is unclear.

--- Document Content ---
{content}
--- End ---

Return ONLY a valid JSON array of fact objects with category, content, structured_data, and confidence_score. Extract up to {max_facts} facts."""

FACT_GAP_CHECK_PROMPT_TEMPLATE = """Review the document content for missed objective facts.

Extraction mode: coverage gap check. Return only facts that are not already captured.
Document type hint: {doc_type}
Document name: {document_name}
Case type: {case_type}
Document-specific extraction guidance: {doc_type_guidance}
Coverage diagnostics:
{coverage_json}

Existing extracted facts:
{existing_facts_json}

Document content:
{content}

Return ONLY a valid JSON array of additional fact objects with category, content, structured_data, and confidence_score.
Rules:
- Prefer missed facts with dates, names, organizations, titles, roles, publications, patents, awards, memberships, metrics, or quoted source support.
- Do not repeat facts already listed.
- Use structured_data.review_status = "candidate" and structured_data.source when possible.
- Extract at most {max_facts} additional facts."""

RESUME_DOC_TYPE_IDS = {"resume", "cv", "curriculum_vitae", "profile", "bio", "biography"}
RESUME_NAME_MARKERS = ("resume", "cv", "curriculum vitae", "简历", "履历", "个人综述", "个人简介")
RESUME_SECTION_ALIASES = {
    "education": ("education", "educational background", "academic background", "学历", "教育", "教育背景", "学习经历"),
    "employment": ("experience", "employment", "work experience", "professional experience", "appointments", "工作", "任职", "工作经历", "职业经历", "任职经历"),
    "publication": ("publications", "selected publications", "论文", "发表", "学术发表", "代表论文"),
    "patent": ("patents", "专利", "发明"),
    "award": ("awards", "honors", "honours", "prizes", "奖项", "荣誉", "获奖"),
    "membership": ("memberships", "professional service", "service", "committees", "会员", "专业组织", "学术服务", "社会兼职"),
    "peer_review": ("review", "reviewer", "judging", "program committee", "评审", "审稿", "评委", "程序委员会"),
    "project": ("projects", "grants", "funding", "项目", "课题", "基金"),
}


def _truncate_text(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def clean_model_text(value):
    if isinstance(value, str):
        return strip_think_tags(value)
    if isinstance(value, list):
        return [clean_model_text(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_model_text(item) for key, item in value.items()}
    return value


def _looks_like_resume_or_profile(doc_type: str, document_name: str, lawyer_guidance: str) -> bool:
    normalized_type = (doc_type or "").strip().lower()
    if normalized_type in RESUME_DOC_TYPE_IDS:
        return True
    haystack = f"{document_name or ''} {lawyer_guidance or ''}".lower()
    return any(marker in haystack for marker in RESUME_NAME_MARKERS)


def _guidance_for_doc_type(doc_type: str, document_name: str, lawyer_guidance: str) -> tuple[str, str]:
    normalized_type = (doc_type or "evidence").strip().lower()
    if _looks_like_resume_or_profile(normalized_type, document_name, lawyer_guidance):
        return "resume", DOC_TYPE_GUIDANCE["resume"]
    if normalized_type.startswith("custom_"):
        return normalized_type, CUSTOM_DOC_TYPE_GUIDANCE
    return normalized_type, DOC_TYPE_GUIDANCE.get(
        normalized_type,
        "Focus on objective facts, source-backed details, dates, names, numbers, and legal relevance. If the document is a resume/CV/profile, extract verifiable background entries as facts.",
    )


def _normalize_heading(value: str) -> str:
    return value.strip().strip(":：").lower()


def _resume_section_for_line(line: str) -> tuple[str, str] | None:
    normalized = _normalize_heading(line)
    if not normalized or len(normalized) > 80:
        return None
    for section, aliases in RESUME_SECTION_ALIASES.items():
        if normalized in aliases:
            return section, ""
        for alias in aliases:
            for marker in (f"{alias}:", f"{alias}："):
                if normalized.startswith(marker):
                    return section, line[len(marker):].strip()
    return None


def _build_resume_inventory(text: str, limit: int = 3200) -> str:
    """Create a compact section map that helps the LLM avoid collapsing CV entries."""
    buckets: dict[str, list[str]] = {}
    current = "profile"
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        section_match = _resume_section_for_line(line)
        if section_match:
            section, inline_entry = section_match
            current = section
            buckets.setdefault(current, [])
            if inline_entry and len(buckets[current]) < 18:
                buckets[current].append(inline_entry[:260])
            continue
        if len(line) < 3:
            continue
        buckets.setdefault(current, [])
        if len(buckets[current]) < 18:
            buckets[current].append(line[:260])

    if not buckets:
        return ""

    parts: list[str] = []
    for section in ("education", "employment", "publication", "patent", "award", "membership", "peer_review", "project", "profile"):
        entries = buckets.get(section) or []
        if not entries:
            continue
        parts.append(f"{section}:\n" + "\n".join(f"- {entry}" for entry in entries[:12]))
    inventory = "\n\n".join(parts)
    if not inventory:
        return ""
    return "\nResume/CV parsing aid. Use this section map to split facts; do not copy unsupported entries:\n" + _truncate_text(inventory, limit)


def _needs_low_yield_resume_retry(doc_type_hint: str, facts: list[dict], text_chars: int) -> bool:
    return doc_type_hint == "resume" and text_chars >= 300 and len(facts) < 3


def _normalize_fact_identity(fact: dict) -> str:
    content = re.sub(r"\s+", " ", str(fact.get("content") or "")).strip().lower()
    category = str(fact.get("category") or "other").strip().lower()
    return f"{category}:{content[:260]}"


def _dedupe_facts(facts: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        content = str(fact.get("content") or "").strip()
        if not content:
            continue
        identity = _normalize_fact_identity(fact)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(fact)
    return deduped


def _split_text_chunks(text: str, max_chars: int, max_chunks: int, overlap_chars: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            if len(chunks) >= max_chunks:
                break
            overlap = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = f"{overlap}\n\n{paragraph}".strip()
        else:
            chunks.append(paragraph[:max_chars])
            if len(chunks) >= max_chunks:
                break
            current = paragraph[max(0, max_chars - overlap_chars):]
    if current and len(chunks) < max_chunks:
        chunks.append(current[:max_chars])
    return chunks or [text[:max_chars]]


def _candidate_signal_lines(text: str, limit: int = 80) -> list[str]:
    lines: list[str] = []
    signal_pattern = re.compile(r"(\b(19|20)\d{2}\b|\d+|:|：|Ph\.?D|M\.?S|B\.?S|Patent|Publication|Award|审稿|专利|论文|奖|任职|教育)", re.I)
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if len(line) < 5:
            continue
        if signal_pattern.search(line):
            lines.append(line[:220])
        if len(lines) >= limit:
            break
    return lines


def _coverage_diagnostics(text: str, facts: list[dict], doc_type_hint: str) -> dict:
    unique_years = sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", text)))
    candidate_lines = _candidate_signal_lines(text)
    sections = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if _resume_section_for_line(line):
            sections.append(line[:80])
    categories = sorted({str(fact.get("category") or "other") for fact in facts})
    expected_floor = 1
    if doc_type_hint == "resume":
        expected_floor = min(settings.PARSE_RESUME_MAX_FACTS, max(4, len(sections) * 2, len(unique_years), len(candidate_lines) // 2))
    else:
        expected_floor = min(settings.PARSE_MAX_FACTS, max(2, len(sections), len(unique_years) // 2, len(candidate_lines) // 3))
    fact_count = len(facts)
    coverage_score = min(1.0, fact_count / expected_floor) if expected_floor else 1.0
    potential_gap_count = max(0, expected_floor - fact_count)
    return {
        "text_chars": len(text.strip()),
        "candidate_signal_count": len(candidate_lines),
        "candidate_signal_samples": candidate_lines[:12],
        "unique_year_count": len(unique_years),
        "unique_year_samples": unique_years[:20],
        "section_count": len(sections),
        "section_samples": sections[:12],
        "fact_count": fact_count,
        "expected_min_fact_count": expected_floor,
        "coverage_score": round(coverage_score, 2),
        "potential_gap_count": potential_gap_count,
        "categories": categories,
    }


def _should_run_gap_check(diagnostics: dict, doc_type_hint: str, fallback_used: bool) -> bool:
    if fallback_used:
        return False
    if diagnostics.get("text_chars", 0) < 300:
        return False
    if doc_type_hint == "resume" and diagnostics.get("coverage_score", 1) < 0.85:
        return True
    return diagnostics.get("potential_gap_count", 0) >= 3 and diagnostics.get("coverage_score", 1) < 0.7


def _prepare_fact_for_review(fact: dict, *, source_scope: str) -> dict:
    prepared = dict(fact)
    prepared["category"] = str(prepared.get("category") or "other")
    prepared["content"] = strip_think_tags(str(prepared.get("content") or "")).strip()
    try:
        prepared["confidence_score"] = float(prepared.get("confidence_score", 0.75))
    except (TypeError, ValueError):
        prepared["confidence_score"] = 0.75
    structured = dict(prepared.get("structured_data") or {})
    structured.setdefault("review_status", "candidate")
    structured.setdefault("extraction_mode", "high_recall")
    structured.setdefault("source_scope", source_scope)
    prepared["structured_data"] = structured
    return prepared


class FactExtractionAgent:
    def __init__(self, llm: Optional[LLMService] = None):
        self.llm = llm or LLMService()
        self.last_diagnostics: dict = {}

    async def extract_facts(
        self,
        file_path: str,
        mime_type: str = "",
        doc_type: str = "evidence",
        case_type: str = "EB1A",
        lawyer_guidance: str = "",
        max_content_chars: Optional[int] = None,
        document_name: str = "",
    ) -> list[dict]:
        """
        Extract facts from a document file.
        Returns list of fact dicts ready to be inserted into the facts table.
        """
        max_content_chars = max_content_chars or settings.PARSE_MAX_CONTENT_CHARS

        self.last_diagnostics = {
            "doc_type": doc_type,
            "document_name": document_name,
            "text_chars": 0,
            "content_chars": 0,
            "text_quality": "unknown",
            "fallback_retry_used": False,
            "llm_response_chars": 0,
            "llm_response_snippet": "",
        }

        # 1. Parse text
        raw_text = extract_text_from_file(file_path, mime_type, max_chars=max_content_chars)
        stripped_text = raw_text.strip()
        text_chars = len(stripped_text)
        self.last_diagnostics["text_chars"] = text_chars
        self.last_diagnostics["ocr_used"] = "[OCR page " in stripped_text[:500]
        if text_chars < settings.PARSE_MIN_READABLE_TEXT_CHARS:
            logger.warning(f"No text extracted from {file_path}")
            self.last_diagnostics["text_quality"] = "unreadable"
            raise DocumentTextExtractionError(
                "No readable text was extracted from this document. The file may be scanned, image-only, encrypted, or too short after extraction."
            )
        self.last_diagnostics["text_quality"] = "short" if text_chars < 200 else "readable"

        guidance = _truncate_text(lawyer_guidance, settings.PARSE_MAX_LAWYER_GUIDANCE_CHARS)
        doc_type_hint, doc_type_guidance = _guidance_for_doc_type(doc_type, document_name, guidance)
        self.last_diagnostics["resolved_doc_type"] = doc_type_hint
        resume_inventory = _build_resume_inventory(raw_text) if doc_type_hint == "resume" else ""
        self.last_diagnostics["resume_inventory_chars"] = len(resume_inventory)
        max_facts = settings.PARSE_RESUME_MAX_FACTS if doc_type_hint == "resume" else settings.PARSE_MAX_FACTS
        max_output_tokens = settings.PARSE_RESUME_MAX_OUTPUT_TOKENS if doc_type_hint == "resume" else settings.PARSE_MAX_OUTPUT_TOKENS
        self.last_diagnostics["max_facts"] = max_facts

        chunks = _split_text_chunks(
            raw_text,
            max_chars=min(max_content_chars, settings.PARSE_CHUNK_MAX_CHARS),
            max_chunks=settings.PARSE_MAX_CHUNKS,
            overlap_chars=settings.PARSE_CHUNK_OVERLAP_CHARS,
        )
        self.last_diagnostics["chunk_count"] = len(chunks)
        self.last_diagnostics["content_chars"] = sum(len(chunk) for chunk in chunks)
        if len(chunks) >= settings.PARSE_MAX_CHUNKS and len(raw_text) > sum(len(chunk) for chunk in chunks):
            self.last_diagnostics["warning"] = "content_truncated_by_chunk_limit"

        facts: list[dict] = []
        primary_response_snippets: list[str] = []
        per_chunk_limit = max(4, min(max_facts, (max_facts // max(1, len(chunks))) + 3))
        for index, chunk in enumerate(chunks, start=1):
            content_scope = f"chunk {index} of {len(chunks)}" if len(chunks) > 1 else "full document"
            prompt = FACT_EXTRACTION_PROMPT_TEMPLATE.format(
                doc_type=doc_type_hint,
                document_name=document_name or "Unknown",
                content_scope=content_scope,
                global_max_facts=max_facts,
                doc_type_guidance=doc_type_guidance,
                case_type=case_type,
                lawyer_guidance=guidance or "No special lawyer guidance provided.",
                resume_inventory=resume_inventory if index == 1 else "",
                content=chunk,
                max_facts=per_chunk_limit,
            )
            raw_response = await self.llm.extract_json(
                prompt,
                system=FACT_EXTRACTION_SYSTEM,
                max_tokens=max_output_tokens,
            )
            primary_response_snippets.append(_truncate_text(strip_think_tags(raw_response or ""), 180))
            parsed_chunk_facts = [
                _prepare_fact_for_review(fact, source_scope=content_scope)
                for fact in self._parse_facts_json(raw_response)
            ]
            facts.extend(parsed_chunk_facts)

        facts = _dedupe_facts(facts)
        self.last_diagnostics["llm_response_chars"] = sum(len(snippet) for snippet in primary_response_snippets)
        self.last_diagnostics["llm_response_snippet"] = "\n---\n".join(primary_response_snippets[:3])
        fallback_used = False

        if not facts or _needs_low_yield_resume_retry(doc_type_hint, facts, text_chars):
            fallback_used = True
            self.last_diagnostics["fallback_retry_used"] = True
            if facts:
                self.last_diagnostics["fallback_reason"] = "low_yield_resume"
            fallback_prompt = FACT_EXTRACTION_FALLBACK_PROMPT_TEMPLATE.format(
                doc_type=doc_type_hint,
                document_name=document_name or "Unknown",
                content_scope="full document retry",
                global_max_facts=max_facts,
                doc_type_guidance=doc_type_guidance,
                case_type=case_type,
                lawyer_guidance=guidance or "No special lawyer guidance provided.",
                resume_inventory=resume_inventory,
                content=self._smart_truncate(raw_text, max_content_chars),
                max_facts=max_facts,
            )
            retry_response = await self.llm.extract_json(
                fallback_prompt,
                system=FACT_EXTRACTION_SYSTEM,
                max_tokens=max_output_tokens,
            )
            self.last_diagnostics["fallback_response_chars"] = len(retry_response or "")
            self.last_diagnostics["fallback_response_snippet"] = _truncate_text(strip_think_tags(retry_response or ""), 240)
            retry_facts = [
                _prepare_fact_for_review(fact, source_scope="full document retry")
                for fact in self._parse_facts_json(retry_response)
            ]
            if len(retry_facts) >= len(facts):
                facts = retry_facts
        coverage = _coverage_diagnostics(raw_text, facts, doc_type_hint)
        if _should_run_gap_check(coverage, doc_type_hint, fallback_used):
            self.last_diagnostics["gap_check_used"] = True
            remaining = max(0, max_facts - len(facts))
            gap_prompt = FACT_GAP_CHECK_PROMPT_TEMPLATE.format(
                doc_type=doc_type_hint,
                document_name=document_name or "Unknown",
                case_type=case_type,
                doc_type_guidance=doc_type_guidance,
                coverage_json=json.dumps(coverage, ensure_ascii=False, indent=2),
                existing_facts_json=json.dumps([
                    {
                        "category": fact.get("category"),
                        "content": fact.get("content"),
                        "source": (fact.get("structured_data") or {}).get("source"),
                    }
                    for fact in facts[:max_facts]
                ], ensure_ascii=False, indent=2),
                content=self._smart_truncate(raw_text, max_content_chars),
                max_facts=max(1, remaining),
            )
            gap_response = await self.llm.extract_json(
                gap_prompt,
                system=FACT_EXTRACTION_SYSTEM,
                max_tokens=max_output_tokens,
            )
            self.last_diagnostics["gap_response_chars"] = len(gap_response or "")
            self.last_diagnostics["gap_response_snippet"] = _truncate_text(strip_think_tags(gap_response or ""), 240)
            gap_facts = [
                _prepare_fact_for_review(fact, source_scope="coverage gap check")
                for fact in self._parse_facts_json(gap_response)
            ]
            facts = _dedupe_facts(facts + gap_facts)

        facts = _dedupe_facts(facts)[:max_facts]
        coverage = _coverage_diagnostics(raw_text, facts, doc_type_hint)
        self.last_diagnostics["coverage"] = coverage
        self.last_diagnostics["fact_count"] = len(facts)
        if not facts:
            self.last_diagnostics["warning"] = "no_facts_extracted_after_retry"
        elif coverage.get("potential_gap_count", 0) > 0 and coverage.get("coverage_score", 1) < 0.75:
            self.last_diagnostics["warning"] = self.last_diagnostics.get("warning") or "possible_parse_gaps"
        logger.info(f"Extracted {len(facts)} facts from {file_path}")
        return facts

    def _smart_truncate(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        # Keep first 70% + last 30% to preserve intro and conclusion
        head = int(max_chars * 0.7)
        tail = max_chars - head
        return text[:head] + f"\n\n[... {len(text) - max_chars} chars omitted ...]\n\n" + text[-tail:]

    def _parse_facts_json(self, raw: str) -> list[dict]:
        import re

        # 1. Strip <think>...</think> reasoning blocks (MiniMax / DeepSeek style)
        raw = strip_think_tags(raw or "")

        # 2. Strip markdown fences
        if raw.startswith("```"):
            parts = raw.split("```")
            # Take the content between first pair of fences
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("```").strip()

        # 3. Find first JSON array in the response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            raw = match.group(0)

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return clean_model_text(data)
            elif isinstance(data, dict) and "facts" in data:
                return clean_model_text(data["facts"])
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse facts JSON: {e}\nRaw snippet: {raw[:300]}")
        return []
