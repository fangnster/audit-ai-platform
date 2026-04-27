import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, CheckCircle, ChevronDown, ChevronUp, Clock, RefreshCw } from 'lucide-react'
import { formatLocalDateTime } from '../utils/time'

export type AgentTask = {
  id: string
  task_type: string
  status: string
  case_id?: string
  case_title?: string
  case_type?: string
  priority?: number
  llm_model?: string | null
  created_at?: string | null
  updated_at?: string | null
  latency_ms?: number
  token_usage?: number
  error_message?: string | null
  input_params?: Record<string, any>
  output_result?: Record<string, any>
  summary?: Record<string, any>
  human_context?: Record<string, any>
}

type Props = {
  tasks: AgentTask[]
  maxItems?: number
  title?: string
  compact?: boolean
  totalItems?: number
}

const typeLabelKey: Record<string, string> = {
  draft_generate: 'agentTaskDraftGenerate',
  rewrite_section: 'agentTaskRewriteSection',
  rfi_generate: 'agentTaskRfiGenerate',
  fact_extract: 'agentTaskFactExtract',
  fact_reparse: 'agentTaskFactReparse',
  merge: 'agentTaskMerge',
  translate: 'agentTaskTranslate',
}

const statusLabelKey: Record<string, string> = {
  queued: 'agentTaskQueued',
  processing: 'agentTaskProcessing',
  completed: 'agentTaskCompleted',
  failed: 'agentTaskFailed',
  cancelled: 'agentTaskCancelled',
}

const statusIcon = (status: string) => ({
  queued: <Clock size={14} color="var(--warning)" />,
  processing: <RefreshCw size={14} color="var(--accent-primary)" className="spin" />,
  completed: <CheckCircle size={14} color="var(--success)" />,
  failed: <AlertCircle size={14} color="var(--danger)" />,
  cancelled: <AlertCircle size={14} color="var(--text-muted)" />,
}[status] ?? <Clock size={14} />)

const statusClass = (status: string) => (
  status === 'completed' ? 'badge-green' : status === 'failed' ? 'badge-red' : status === 'processing' ? 'badge-blue' : 'badge-gray'
)

const isPlainObject = (value: unknown): value is Record<string, any> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
)

const sanitizeDisplayValue = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(sanitizeDisplayValue)
  if (!isPlainObject(value)) return value
  return Object.entries(value).reduce<Record<string, unknown>>((acc, [key, item]) => {
    const normalized = key.toLowerCase()
    if (normalized === 'id' || normalized.endsWith('_id') || normalized.endsWith('_ids')) return acc
    acc[key] = sanitizeDisplayValue(item)
    return acc
  }, {})
}

const stringifyValue = (value: unknown, language: string): string => {
  if (value === undefined || value === null || value === '') return language === 'zh' ? '无' : 'None'
  if (typeof value === 'boolean') return language === 'zh' ? (value ? '是' : '否') : (value ? 'Yes' : 'No')
  if (Array.isArray(value)) return value.map(item => (
    isPlainObject(item)
      ? (item.title || item.name || item.label || item.content || JSON.stringify(item))
      : String(item)
  )).join('、')
  if (isPlainObject(value)) return JSON.stringify(sanitizeDisplayValue(value), null, 2)
  return String(value)
}

const readableListItems = (value: unknown, language: string): string[] => {
  if (Array.isArray(value)) {
    return value
      .map(item => {
        if (isPlainObject(item)) return item.title || item.name || item.label || item.content || stringifyValue(item, language)
        return String(item)
      })
      .map(item => String(item).trim())
      .filter(Boolean)
  }
  const text = stringifyValue(value, language).trim()
  if (!text || text === '无' || text === 'None') return []
  return [text]
}

function renderDetailValue(key: string, value: unknown, language: string) {
  if (key === 'fact_titles') {
    const items = readableListItems(value, language)
    if (items.length === 0) return <pre>{language === 'zh' ? '无' : 'None'}</pre>
    return <pre>{items.join('\n')}</pre>
  }
  return <pre>{stringifyValue(value, language)}</pre>
}

const shortValue = (value: unknown, language: string, limit = 180): string => {
  const text = stringifyValue(value, language)
  return text.length > limit ? `${text.slice(0, limit).trim()}...` : text
}

const pickRows = (payload: Record<string, any>, keys: string[]) => (
  keys
    .filter(key => payload[key] !== undefined && payload[key] !== null && payload[key] !== '')
    .map(key => ({ key, value: payload[key] }))
)

const zhLabels: Record<string, string> = {
  document_name: '文件',
  doc_type: '文件类型',
  case_type: '案件类型',
  facts_extracted: '提取事实数',
  fact_categories: '事实分类',
  prompt: '律师提示',
  prompt_chars: '提示长度',
  prompt_used: '使用提示',
  diagnostics: '解析诊断',
  warning: '告警',
  fact_title: '事实',
  fact_titles: '相关事实',
  fact_category: '事实分类',
  comment: '异议意见',
  comment_chars: '异议长度',
  source_document: '来源文件',
  reparse_source: '重解析来源',
  knowledge_ref_count: '知识库引用数',
  knowledge_refs: '知识库引用',
  source_text_chars: '来源文本长度',
  fallback_used: '是否降级',
  llm_error: '模型错误',
  original_content: '原事实',
  new_content: '新事实',
  title: '标题',
  strategy: '策略',
  strategy_name: '策略',
  fact_count: '使用事实数',
  versions: '生成版本',
  section_title: '文案',
  instruction: '改写要求',
  history_ref_count: '历史引用数',
  text_quality: '文本质量',
  chunk_count: '分块数',
  coverage_score: '覆盖率',
  potential_gap_count: '潜在遗漏',
  mime_type: '文件格式',
  case_title: '案件',
}

const enLabels: Record<string, string> = {
  document_name: 'Document',
  doc_type: 'Document type',
  case_type: 'Case type',
  facts_extracted: 'Facts extracted',
  fact_categories: 'Fact categories',
  prompt: 'Lawyer guidance',
  prompt_chars: 'Guidance length',
  prompt_used: 'Guidance used',
  diagnostics: 'Parse diagnostics',
  warning: 'Warning',
  fact_title: 'Fact',
  fact_titles: 'Related facts',
  fact_category: 'Fact category',
  comment: 'Dispute comment',
  comment_chars: 'Comment length',
  source_document: 'Source document',
  reparse_source: 'Reparse source',
  knowledge_ref_count: 'Knowledge refs',
  knowledge_refs: 'Knowledge references',
  source_text_chars: 'Source text chars',
  fallback_used: 'Fallback used',
  llm_error: 'Model error',
  original_content: 'Original fact',
  new_content: 'New fact',
  title: 'Title',
  strategy: 'Strategy',
  strategy_name: 'Strategy',
  fact_count: 'Facts used',
  versions: 'Versions',
  section_title: 'Draft',
  instruction: 'Rewrite instruction',
  history_ref_count: 'History refs',
  text_quality: 'Text quality',
  chunk_count: 'Chunks',
  coverage_score: 'Coverage',
  potential_gap_count: 'Potential gaps',
  mime_type: 'MIME type',
  case_title: 'Case',
}

function labelFor(key: string, language: string) {
  const labels = language === 'zh' ? zhLabels : enLabels
  return labels[key] || key
}

function detailKeys(taskType: string, section: 'input' | 'output') {
  if (taskType === 'fact_extract') {
    return section === 'input'
      ? ['document_name', 'doc_type', 'case_type', 'mime_type', 'prompt_chars', 'prompt']
      : ['facts_extracted', 'fact_categories', 'warning', 'diagnostics']
  }
  if (taskType === 'fact_reparse') {
    return section === 'input'
      ? ['fact_title', 'fact_category', 'comment', 'knowledge_refs', 'original_content']
      : ['source_document', 'reparse_source', 'knowledge_ref_count', 'fallback_used', 'llm_error', 'original_content', 'new_content']
  }
  if (taskType === 'draft_generate') {
    return section === 'input'
      ? ['title', 'strategy_name', 'prompt', 'knowledge_refs', 'fact_titles']
      : ['versions', 'fact_count', 'knowledge_ref_count', 'history_ref_count']
  }
  if (taskType === 'rewrite_section') {
    return section === 'input'
      ? ['section_title', 'instruction', 'strategy_name', 'knowledge_refs', 'fact_titles']
      : ['section_title', 'strategy_name', 'knowledge_ref_count', 'history_ref_count']
  }
  return section === 'input' ? Object.keys({}) : Object.keys({})
}

function readablePayload(task: AgentTask, section: 'input' | 'output'): Record<string, any> {
  const input = task.input_params || {}
  const output = task.output_result || {}
  const human = task.human_context || {}
  const document = human.document || {}
  const sourceDocument = human.source_document || {}
  const fact = human.fact || {}
  const sectionInfo = human.section || {}
  const knowledgeRefs = human.knowledge_refs || input.knowledge_refs || output.knowledge_refs
  const factTitles = Array.isArray(human.facts) ? human.facts.map((item: any) => item.title || item.content).filter(Boolean) : undefined

  if (task.task_type === 'fact_extract') {
    return section === 'input'
      ? {
        document_name: document.name || input.document_name,
        doc_type: document.type || input.doc_type,
        case_type: input.case_type,
        mime_type: input.mime_type,
        prompt_chars: input.prompt_chars,
        prompt: input.prompt,
      }
      : output
  }
  if (task.task_type === 'fact_reparse') {
    return section === 'input'
      ? {
        fact_title: fact.title,
        fact_category: fact.category || input.fact_category,
        comment: input.comment,
        knowledge_refs: knowledgeRefs,
        original_content: input.original_content,
      }
      : {
        ...output,
        source_document: sourceDocument.name || output.source_document,
      }
  }
  if (task.task_type === 'draft_generate') {
    return section === 'input'
      ? {
        title: input.title,
        strategy_name: human.strategy_name || input.strategy,
        prompt: input.prompt,
        knowledge_refs: knowledgeRefs,
        fact_titles: factTitles,
      }
      : output
  }
  if (task.task_type === 'rewrite_section') {
    return section === 'input'
      ? {
        section_title: sectionInfo.title,
        instruction: input.instruction,
        strategy_name: human.strategy_name || input.strategy,
        knowledge_refs: knowledgeRefs,
        fact_titles: factTitles,
      }
      : {
        ...output,
        section_title: sectionInfo.title,
        strategy_name: human.strategy_name || output.strategy,
      }
  }
  return section === 'input' ? input : output
}

function summaryChips(task: AgentTask, language: string) {
  const summary = task.summary || {}
  const output = task.output_result || {}
  const input = task.input_params || {}
  const human = task.human_context || {}
  const merged: Record<string, any> = {
    case_title: task.case_title,
    case_type: task.case_type,
    ...input,
    ...summary,
    ...output,
    document_name: human.document?.name || summary.document_name || output.document_name || input.document_name,
    source_document: human.source_document?.name || output.source_document,
    fact_title: human.fact?.title,
    section_title: human.section?.title,
    strategy_name: human.strategy_name || summary.strategy || input.strategy || output.strategy,
  }
  const keys = task.task_type === 'fact_extract'
    ? ['case_title', 'document_name', 'doc_type', 'facts_extracted', 'text_quality', 'chunk_count', 'potential_gap_count', 'warning']
    : task.task_type === 'fact_reparse'
      ? ['case_title', 'fact_title', 'source_document', 'knowledge_ref_count', 'source_text_chars', 'fallback_used']
      : task.task_type === 'draft_generate'
        ? ['case_title', 'title', 'strategy_name', 'fact_count', 'knowledge_ref_count']
        : task.task_type === 'rewrite_section'
          ? ['case_title', 'section_title', 'strategy_name', 'knowledge_ref_count', 'history_ref_count']
          : Object.keys(summary).slice(0, 4)
  return keys
    .filter(key => merged[key] !== undefined && merged[key] !== null && merged[key] !== '')
    .map(key => ({ label: labelFor(key, language), value: shortValue(merged[key], language, 72) }))
}

export function AgentRunLogPanel({ tasks, maxItems = 8, title, compact = false, totalItems }: Props) {
  const { t, i18n } = useTranslation()
  const language = i18n.language
  const visibleTasks = useMemo(() => tasks.slice(0, maxItems), [tasks, maxItems])
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set(visibleTasks.slice(0, 1).map(task => task.id)))

  useEffect(() => {
    if (visibleTasks.length === 0) return
    setExpandedIds(prev => (
      visibleTasks.some(task => prev.has(task.id)) ? prev : new Set([visibleTasks[0].id])
    ))
  }, [visibleTasks])

  if (tasks.length === 0) return null
  const displayTotal = totalItems ?? tasks.length

  const toggleExpanded = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="card agent-run-log-panel">
      <div className="agent-run-log-header">
        <div>
          <div className="agent-run-log-title">📋 {title || t('agentRunLog')}</div>
          <div className="agent-run-log-subtitle">
            {language === 'zh' ? `显示 ${visibleTasks.length} 条，共 ${displayTotal} 条` : `${visibleTasks.length} shown of ${displayTotal} total`}
          </div>
        </div>
      </div>

      <div className="agent-run-log-list">
        {visibleTasks.map(task => {
          const expanded = expandedIds.has(task.id)
          const inputRows = pickRows(readablePayload(task, 'input'), detailKeys(task.task_type, 'input'))
          const outputRows = pickRows(readablePayload(task, 'output'), detailKeys(task.task_type, 'output'))
          const chips = summaryChips(task, language)
          return (
            <div key={task.id} className="agent-run-task">
              <button className="agent-run-task-main" onClick={() => toggleExpanded(task.id)} type="button">
                <span className="agent-run-task-icon">{statusIcon(task.status)}</span>
                <span className="agent-run-task-name">
                  {typeLabelKey[task.task_type] ? t(typeLabelKey[task.task_type]) : task.task_type}
                </span>
                <span className={`badge ${statusClass(task.status)}`}>
                  {statusLabelKey[task.status] ? t(statusLabelKey[task.status]) : task.status}
                </span>
                {task.llm_model && <span className="agent-run-meta">{task.llm_model}</span>}
                <span className="agent-run-time">
                  {task.latency_ms ? `${Math.round(task.latency_ms / 1000)}s · ` : ''}
                  {formatLocalDateTime(task.updated_at || task.created_at, language)}
                </span>
                {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
              </button>

              {chips.length > 0 && (
                <div className="agent-run-chip-row">
                  {chips.map(chip => (
                    <span key={`${task.id}-${chip.label}`} className="agent-run-chip">
                      {chip.label}: {chip.value}
                    </span>
                  ))}
                </div>
              )}

              {task.status === 'failed' && task.error_message && (
                <div className="agent-run-error">{task.error_message}</div>
              )}

              {expanded && !compact && (
                <div className="agent-run-detail-grid">
                  <div className="agent-run-detail-block">
                    <div className="agent-run-detail-title">{language === 'zh' ? '输入' : 'Input'}</div>
                    {inputRows.length === 0 ? (
                      <div className="agent-run-empty">{language === 'zh' ? '无可展示输入' : 'No input details'}</div>
                    ) : inputRows.map(row => (
                      <div key={row.key} className="agent-run-detail-row">
                        <span>{labelFor(row.key, language)}</span>
                        {renderDetailValue(row.key, row.value, language)}
                      </div>
                    ))}
                  </div>

                  <div className="agent-run-detail-block">
                    <div className="agent-run-detail-title">{language === 'zh' ? '结果与诊断' : 'Result and Diagnostics'}</div>
                    {outputRows.length === 0 ? (
                      <div className="agent-run-empty">{language === 'zh' ? '任务尚未产生结果' : 'No result yet'}</div>
                    ) : outputRows.map(row => (
                      <div key={row.key} className="agent-run-detail-row">
                        <span>{labelFor(row.key, language)}</span>
                        {renderDetailValue(row.key, row.value, language)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
