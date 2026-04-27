import uuid
import json
from types import SimpleNamespace

import pytest

from app.models.draft import DraftSection, SectionStatus
from app.agents.draft_generator import DraftGenerationOrchestrator
from app.agents.draft_generator import DraftGenerationAgent
from app.llm.provider import strip_think_tags
from app.workers.agent_tasks import _full_draft_from_content, _split_into_sections
from app.routers import drafts


class FakeScalarResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return FakeScalarResult(self.rows)


class FakeDraftDb:
    def __init__(self, sections, case=None):
        self.sections = sections
        self.case = case

    async def execute(self, query):
        return FakeResult(self.sections)

    async def get(self, model, section_id):
        if getattr(model, "__name__", "") == "Case" and self.case and self.case.id == section_id:
            return self.case
        return next((section for section in self.sections if section.id == section_id), None)


class FakeLLM:
    def __init__(self):
        self.prompt = ""
        self.system = ""
        self.max_tokens = 0

    async def generate(self, prompt, system="", temperature=0.3, max_tokens=4096):
        self.prompt = prompt
        self.system = system
        self.max_tokens = max_tokens
        return """# EB-1A Petition Letter for Dr. Lin

## Awards and Original Contributions
The record combines the national award certificate, recommendation letter, patent file, and citation report to establish sustained acclaim."""


def make_section(
    case_id: uuid.UUID,
    title: str = "测试文案标题",
    content: str = "This is downloadable draft content.",
    version: str = "b",
) -> DraftSection:
    return DraftSection(
        id=uuid.uuid4(),
        case_id=case_id,
        section_order=1,
        section_title=title,
        content=content,
        status=SectionStatus.draft,
        version=version,
        is_deleted=False,
        pending_slots={},
    )


def make_case(case_id: uuid.UUID, title: str = "张三 EB-1A 案件", case_type: str = "EB1A"):
    return SimpleNamespace(id=case_id, title=title, case_type=case_type)


def test_split_uses_generated_top_title_and_strips_thinking_block():
    content = """<think>
Internal analysis that should never become a user-facing section.
</think>
# EB-1A Petition Letter for Zhang San

## Introduction
Intro body.

## Criterion One
Evidence body."""

    sections = _split_into_sections(content)

    assert sections[0][0] == "EB-1A Petition Letter for Zhang San"
    assert sections[0][1].startswith("Introduction")
    assert sections[1] == ("Criterion One", "Evidence body.")


def test_strip_think_tags_removes_reasoning_from_any_llm_output():
    content = "Before<think>hidden reasoning</think>\nVisible answer"

    assert strip_think_tags(content) == "Before\nVisible answer"


def test_split_uses_requested_title_when_model_starts_with_section_header():
    content = """## Introduction
Intro body.

## Evidence
Evidence body."""

    sections = _split_into_sections(content, draft_title="Custom Petition Title")

    assert sections[0][0] == "Custom Petition Title"
    assert sections[0][1].startswith("Introduction")
    assert sections[1] == ("Evidence", "Evidence body.")


def test_full_draft_keeps_internal_headings_as_one_artifact():
    title, body = _full_draft_from_content("""# EB-1A Petition Letter

## Introduction
Intro body.

## Evidence
Evidence body.""")

    assert title == "EB-1A Petition Letter"
    assert "## Introduction" in body
    assert "## Evidence" in body


def test_orchestrator_selects_cross_document_facts_for_one_argument():
    facts = [
        {
            "id": "fact-award",
            "category": "award",
            "content": "The beneficiary won a nationally recognized research award.",
            "source_document_id": "doc-award",
            "structured_data": {"document_name": "award_certificate.pdf"},
            "confidence_score": 0.96,
        },
        {
            "id": "fact-evidence",
            "category": "evidence",
            "content": "A recommendation letter explains that the award is granted to top researchers.",
            "source_document_id": "doc-letter",
            "structured_data": {"document_name": "recommendation_letter.pdf"},
            "confidence_score": 0.91,
        },
    ]

    plan = DraftGenerationOrchestrator(
        facts=facts,
        case_type="EB1A",
        criteria=["criterion_1"],
    ).build_plan()

    selected_doc_ids = {
        fact.source.document_id
        for argument in plan.arguments
        for fact in argument.selected_facts
    }
    assert {"doc-award", "doc-letter"}.issubset(selected_doc_ids)


@pytest.mark.asyncio
async def test_generate_draft_prompt_contains_cross_document_evidence():
    facts = [
        {
            "id": "fact-award",
            "category": "award",
            "content": "Dr. Lin won the National Biomedical Innovation Award in 2024.",
            "source_document_id": "doc-award",
            "structured_data": {"document_name": "award_certificate.pdf", "quote": "National Biomedical Innovation Award"},
            "confidence_score": 0.98,
        },
        {
            "id": "fact-letter",
            "category": "evidence",
            "content": "The recommender states the award is given to fewer than 1% of researchers in the field.",
            "source_document_id": "doc-letter",
            "structured_data": {"document_name": "expert_recommendation.pdf"},
            "confidence_score": 0.94,
        },
        {
            "id": "fact-patent",
            "category": "patent",
            "content": "The patented diagnostic workflow has been adopted by three hospital systems.",
            "source_document_id": "doc-patent",
            "structured_data": {"document_name": "patent_record.pdf"},
            "confidence_score": 0.93,
        },
    ]

    llm = FakeLLM()
    content = await DraftGenerationAgent(llm=llm).generate_draft(
        facts=facts,
        case_type="EB1A",
        criteria=["criterion_1", "criterion_5"],
        draft_title="EB-1A Petition Letter for Dr. Lin",
    )

    assert content.startswith("# EB-1A Petition Letter")
    assert "LEGAL ARGUMENT CONTEXT" in llm.prompt
    assert "CROSS-DOCUMENT EVIDENCE ORGANIZATION" in llm.prompt
    assert "RELEVANT LEGAL CRITERIA" in llm.prompt
    assert "award_certificate.pdf" in llm.prompt
    assert "expert_recommendation.pdf" in llm.prompt
    assert "patent_record.pdf" in llm.prompt
    plan_json = llm.prompt.split("CROSS-DOCUMENT EVIDENCE ORGANIZATION:\n", 1)[1].split("\n\nRELEVANT LEGAL CRITERIA", 1)[0]
    plan = json.loads(plan_json)
    all_sources = {
        evidence["source"]["document_id"]
        for argument in plan["arguments"]
        for evidence in argument["evidence"]
    }
    assert {"doc-award", "doc-letter", "doc-patent"}.issubset(all_sources)


@pytest.mark.asyncio
async def test_generate_draft_prompt_prioritizes_lawyer_custom_format():
    facts = [
        {
            "id": "fact-summary",
            "category": "employment",
            "content": "Dr. Lin led a diagnostic AI deployment across three hospital systems in 2024.",
            "source_document_id": "doc-employment",
            "structured_data": {"document_name": "employment_letter.pdf"},
            "confidence_score": 0.95,
        },
    ]
    custom_instruction = "请生成中文客户背景摘要，章节为：核心优势、关键事实、证据缺口、后续策略。不要写申请信。\n- 按用户指定章节逐项展开；只有明确要求法律要件时才对应法定标准。"

    llm = FakeLLM()
    await DraftGenerationAgent(llm=llm).generate_draft(
        facts=facts,
        case_type="EB1A",
        draft_title="客户背景摘要",
        user_prompt=custom_instruction,
        strategy="criterion",
        knowledge_refs=[
            {
                "title": "客户摘要模板",
                "type": "document_template",
                "content": "使用短段落和项目符号列出背景、证据、风险和下一步。",
            }
        ],
    )

    assert "LAWYER'S REQUIRED FORMAT AND CONTENT INSTRUCTIONS" in llm.prompt
    assert "客户背景摘要" in llm.prompt
    assert custom_instruction in llm.prompt
    assert "客户摘要模板" in llm.prompt
    assert "Do not default to any fixed legacy format" in llm.prompt
    assert "Do not use a USCIS filing-letter structure" in llm.prompt
    assert "CUSTOM DOCUMENT ORGANIZATION" in llm.prompt
    assert "No legal criteria context was injected" in llm.prompt
    assert "LEGAL ARGUMENT CONTEXT" not in llm.prompt
    assert "CROSS-DOCUMENT EVIDENCE ORGANIZATION" not in llm.prompt
    assert "RELEVANT LEGAL CRITERIA" not in llm.prompt
    assert "petition letter" not in llm.prompt.lower()
    assert "petition letter" not in llm.system.lower()


@pytest.mark.asyncio
async def test_generate_draft_compacts_large_inputs_for_remote_llm():
    facts = [
        {
            "id": f"fact-{idx}",
            "category": "evidence",
            "content": "Long fact content " + ("x" * 2000),
            "source_document_id": f"doc-{idx}",
            "structured_data": {"document_name": f"doc-{idx}.pdf", "quote": "quote " + ("y" * 1200)},
            "confidence_score": 0.9,
        }
        for idx in range(40)
    ]
    knowledge_refs = [
        {
            "title": f"Template {idx}",
            "type": "document_template",
            "content": "Knowledge content " + ("z" * 3000),
        }
        for idx in range(8)
    ]

    llm = FakeLLM()
    await DraftGenerationAgent(llm=llm).generate_draft(
        facts=facts,
        case_type="EB1A",
        draft_title="客户背景摘要",
        user_prompt="请生成中文摘要，不要写申请信。",
        knowledge_refs=knowledge_refs,
    )

    assert llm.max_tokens <= 1800
    assert "fact-24" not in llm.prompt
    assert "Template 4" not in llm.prompt
    assert "x" * 1000 not in llm.prompt
    assert "y" * 400 not in llm.prompt
    assert "z" * 1500 not in llm.prompt


def test_draft_attachment_header_supports_chinese_filename():
    header = drafts.attachment_headers("获奖证明文案.docx")["Content-Disposition"]

    header.encode("latin-1")
    assert "filename=" in header
    assert "filename*=UTF-8''" in header


@pytest.mark.asyncio
async def test_export_drafts_docx_returns_non_empty_word_file():
    case_id = uuid.uuid4()
    section = make_section(case_id, content="Downloadable full draft body.")

    response = await drafts.export_drafts(
        case_id,
        version="b",
        format="docx",
        current_user=object(),
        db=FakeDraftDb([section], case=make_case(case_id)),
    )

    assert response.body.startswith(b"PK")
    assert len(response.body) > 1000
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert response.headers["content-length"] == str(len(response.body))
    assert "filename=" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_export_section_txt_returns_title_and_content():
    case_id = uuid.uuid4()
    section = make_section(case_id, title="客户陈述", content="Single section export body.")

    response = await drafts.export_section(
        section.id,
        format="txt",
        current_user=object(),
        db=FakeDraftDb([section], case=make_case(case_id)),
    )
    text = response.body.decode("utf-8")

    assert "客户陈述" in text
    assert "案件名称：张三 EB-1A 案件" in text
    assert "案件类型：EB1A" in text
    assert "生成时间：" in text
    assert "Single section export body." in text
    assert response.headers["content-length"] == str(len(response.body))
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
