from types import SimpleNamespace

from app.routers.documents import _fact_trace_pairs
from app.workers.agent_tasks import _format_draft_reference_appendix


def test_fact_trace_pairs_include_readable_source_fields():
    fact = SimpleNamespace(
        structured_data={
            "page": "p. 3",
            "quote": "Original evidence excerpt",
            "source": "Uploaded CV",
            "title": "Selected project",
        }
    )

    pairs = _fact_trace_pairs(fact, document_name="resume.pdf", document_type="个人简历")

    assert ("来源文件", "resume.pdf") in pairs
    assert ("上传文件类型", "个人简历") in pairs
    assert ("页码/位置", "p. 3") in pairs
    assert ("原文摘录", "Original evidence excerpt") in pairs
    assert ("原始来源说明", "Uploaded CV") in pairs


def test_draft_reference_appendix_is_lawyer_readable():
    appendix = _format_draft_reference_appendix(
        fact_refs=[
            {
                "title": "1. [publication] Published article in Nature",
                "source_document": "publication.pdf",
                "document_type": "学术发表",
                "page": "p. 2",
                "quote": "Article details",
            }
        ],
        document_refs=[
            {
                "name": "publication.pdf",
                "document_type": "学术发表",
                "fact_count": 1,
            }
        ],
    )

    assert "生成依据 / 溯源追踪" in appendix
    assert "publication.pdf（学术发表，引用事实 1 条）" in appendix
    assert "1. [publication] Published article in Nature" in appendix
    assert "页码/位置：p. 2" in appendix
    assert "原文摘录：Article details" in appendix
