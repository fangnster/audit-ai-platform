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
import uuid
from pathlib import Path
from typing import Optional

from app.llm.provider import LLMService, strip_think_tags

logger = logging.getLogger(__name__)


# ── Document text extraction ──────────────────────────────────────────────────

def extract_text_from_file(file_path: str, mime_type: str = "") -> str:
    """Extract plain text from PDF, Word, or image file."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf" or "pdf" in mime_type:
        return _extract_pdf(file_path)
    elif suffix in (".docx", ".doc") or "word" in mime_type:
        return _extract_docx(file_path)
    elif suffix in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        return _extract_image_ocr(file_path)
    elif suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    else:
        # Fallback: try PDF then plain text
        try:
            return _extract_pdf(file_path)
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore")


def _extract_pdf(file_path: str) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        return "\n\n".join(page.get_text() for page in doc)
    except ImportError:
        logger.warning("PyMuPDF not installed, falling back to plain read")
        return Path(file_path).read_text(encoding="utf-8", errors="ignore")


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


# ── Fact extraction via LLM ───────────────────────────────────────────────────

FACT_EXTRACTION_SYSTEM = """You are an expert immigration lawyer assistant specializing in EB-1A, EB-1B, NIW, and O-1A petitions.
Extract all relevant facts from the provided document that could support an immigration petition.
Classify each fact into one of: award, patent, publication, citation, employment, media, membership, education, salary, other.
Return ONLY a valid JSON array — no markdown, no explanation."""

FACT_EXTRACTION_PROMPT_TEMPLATE = """Extract structured facts from the following document for an immigration petition.

Document type hint: {doc_type}
Case type: {case_type}
Lawyer guidance:
{lawyer_guidance}

--- Document Content ---
{content}
--- End ---

Return a JSON array of facts. Each fact object must have:
{{
  "category": "<award|patent|publication|citation|employment|media|membership|education|salary|other>",
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

Extract ALL facts relevant to EB-1A criteria (extraordinary ability evidence).
Output JSON array only."""


def clean_model_text(value):
    if isinstance(value, str):
        return strip_think_tags(value)
    if isinstance(value, list):
        return [clean_model_text(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_model_text(item) for key, item in value.items()}
    return value


class FactExtractionAgent:
    def __init__(self, llm: Optional[LLMService] = None):
        self.llm = llm or LLMService()

    async def extract_facts(
        self,
        file_path: str,
        mime_type: str = "",
        doc_type: str = "evidence",
        case_type: str = "EB1A",
        lawyer_guidance: str = "",
        max_content_chars: int = 12000,
    ) -> list[dict]:
        """
        Extract facts from a document file.
        Returns list of fact dicts ready to be inserted into the facts table.
        """
        # 1. Parse text
        raw_text = extract_text_from_file(file_path, mime_type)
        if not raw_text.strip():
            logger.warning(f"No text extracted from {file_path}")
            return []

        # Truncate to avoid token limits (keep first + last sections)
        content = self._smart_truncate(raw_text, max_content_chars)

        # 2. Build prompt
        prompt = FACT_EXTRACTION_PROMPT_TEMPLATE.format(
            doc_type=doc_type,
            case_type=case_type,
            lawyer_guidance=lawyer_guidance.strip() or "No special lawyer guidance provided.",
            content=content,
        )

        # 3. Call LLM
        raw_response = await self.llm.extract_json(prompt, system=FACT_EXTRACTION_SYSTEM)

        # 4. Parse JSON
        facts = self._parse_facts_json(raw_response)
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
        raw = strip_think_tags(raw)

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
