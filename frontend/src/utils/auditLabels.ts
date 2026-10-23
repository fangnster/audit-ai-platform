// Display labels only. Legacy API values stay unchanged for stored project compatibility.
const AUDIT_TYPES: Record<string, [string, string]> = {
  EB1A: ['财务审计', 'Financial Audit'],
  EB1B: ['内部审计', 'Internal Audit'],
  NIW: ['合规审计', 'Compliance Audit'],
  O1A: ['运营审计', 'Operational Audit'],
  EB2: ['信息技术审计', 'IT Audit'],
  EB3: ['专项审计', 'Special Audit'],
  H1B: ['其他审计', 'Other Audit'],
}

export function auditTypeLabel(value: string, language: string) {
  return AUDIT_TYPES[value]?.[language.startsWith('zh') ? 0 : 1] || value
}

const AUDIT_FACT_CATEGORIES: Record<string, [string, string]> = {
  evidence: ['审计证据', 'Audit Evidence'],
  award: ['财务报表', 'Financial Statements'],
  original_contribution: ['内部控制', 'Internal Controls'],
  patent: ['合同与协议', 'Contracts and Agreements'],
  publication: ['会计记录', 'Accounting Records'],
  citation: ['交易明细', 'Transaction Details'],
  employment: ['薪酬与人事', 'Payroll and Personnel'],
  media: ['外部资料', 'External Information'],
  membership: ['政策与制度', 'Policies and Procedures'],
  resume: ['业务流程', 'Business Processes'],
  reference_letter: ['函证与声明', 'Confirmations and Representations'],
  petition_letter: ['审计报告', 'Audit Report'],
  rfi: ['审计询证回复', 'Audit Inquiry Response'],
  salary: ['薪酬', 'Compensation'],
  education: ['培训记录', 'Training'],
  legal_precedent: ['审计准则', 'Audit Standards'],
  internet_research: ['外部研究', 'External Research'],
  other: ['其他', 'Other'],
}

export function auditFactCategoryLabel(value: string, language: string) {
  return AUDIT_FACT_CATEGORIES[value]?.[language.startsWith('zh') ? 0 : 1] || value
}
