"""Audit display names for legacy stored case-type codes (no data migration)."""

CASE_TYPE_LABELS = {
    "EB1A": "Financial Audit / 财务审计",
    "EB1B": "Internal Audit / 内部审计",
    "NIW": "Compliance Audit / 合规审计",
    "O1A": "Operational Audit / 运营审计",
    "EB2": "IT Audit / 信息技术审计",
    "EB3": "Special Audit / 专项审计",
    "H1B": "Other Audit / 其他审计",
}


def audit_case_type_label(value) -> str:
    code = str(getattr(value, "value", value) or "")
    return CASE_TYPE_LABELS.get(code, code)
