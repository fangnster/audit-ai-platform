import { useEffect, useState, useCallback, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useDropzone } from 'react-dropzone'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  Upload, File, CheckCircle, Clock, AlertCircle, RefreshCw, Download,
  ChevronLeft, ChevronRight,
  FolderOpen, Award, BookOpen, FileText, Users, Mic, Shield, Mail, Archive, Wand2, Search,
  Settings, Plus, Save, X, Sparkles
} from 'lucide-react'
import { docsApi, draftsApi, knowledgeApi } from '../api'
import { AiWorkModal } from '../components/AiWorkModal'
import type { AgentTask } from '../components/AgentRunLogPanel'
import { ConfirmActionKind, ConfirmActionModal, ObjectLifecycleActions } from '../components/ObjectLifecycleActions'
import { formatLocalDateTime } from '../utils/time'
import { readableLlmError } from '../utils/llmError'

type DocTypeOption = { id: string; label: string; icon?: string; enabled?: boolean; builtin?: boolean }

const DEFAULT_DOC_TYPES: DocTypeOption[] = [
  { id: 'evidence', label: '证据材料', icon: '📄', enabled: true, builtin: true },
  { id: 'award', label: '获奖证明', icon: '🏆', enabled: true, builtin: true },
  { id: 'original_contribution', label: '原创成果', icon: '✨', enabled: true, builtin: true },
  { id: 'patent', label: '专利', icon: '💡', enabled: true, builtin: true },
  { id: 'publication', label: '学术发表', icon: '📝', enabled: true, builtin: true },
  { id: 'citation', label: '引用数据', icon: '📊', enabled: true, builtin: true },
  { id: 'employment', label: '雇佣证明', icon: '💼', enabled: true, builtin: true },
  { id: 'media', label: '媒体报道', icon: '📰', enabled: true, builtin: true },
  { id: 'membership', label: '专业组织', icon: '🏛️', enabled: true, builtin: true },
  { id: 'resume', label: '个人简历', icon: '👤', enabled: true, builtin: true },
  { id: 'reference_letter', label: '推荐信', icon: '✉️', enabled: true, builtin: true },
  { id: 'petition_letter', label: '申请信', icon: '📋', enabled: true, builtin: true },
  { id: 'rfi', label: 'RFI 回复', icon: '📮', enabled: true, builtin: true },
  { id: 'other', label: '其他', icon: '📁', enabled: true, builtin: true },
]
const DOC_TYPE_META: Record<string, { icon: string; labelKey: string }> = {
  evidence: { icon: '📄', labelKey: 'docTypeEvidence' },
  award: { icon: '🏆', labelKey: 'docTypeAward' },
  original_contribution: { icon: '✨', labelKey: 'docTypeOriginalContribution' },
  patent: { icon: '💡', labelKey: 'docTypePatent' },
  publication: { icon: '📝', labelKey: 'docTypePublication' },
  citation: { icon: '📊', labelKey: 'docTypeCitation' },
  employment: { icon: '💼', labelKey: 'docTypeEmployment' },
  media: { icon: '📰', labelKey: 'docTypeMedia' },
  membership: { icon: '🏛️', labelKey: 'docTypeMembership' },
  resume: { icon: '👤', labelKey: 'docTypeResume' },
  reference_letter: { icon: '✉️', labelKey: 'docTypeReferenceLetter' },
  petition_letter: { icon: '📋', labelKey: 'docTypePetitionLetter' },
  rfi: { icon: '📮', labelKey: 'docTypeRfi' },
  other: { icon: '📁', labelKey: 'docTypeOther' },
}
const DOC_TYPE_ICONS: Record<string, React.ReactNode> = {
  award: <Award size={16} />, original_contribution: <Sparkles size={16} />, patent: <BookOpen size={16} />, publication: <FileText size={16} />,
  reference_letter: <Mail size={16} />, membership: <Shield size={16} />, media: <Mic size={16} />,
  employment: <Users size={16} />, resume: <Users size={16} />, evidence: <File size={16} />,
}
const TYPE_ICONS: Record<string, string> = { prompt_template: '🧠', document_template: '📋', sample_document: '📄', agent_strategy: '🎯' }
const PARSE_STATUS_ICONS: Record<string, React.ReactNode> = {
  pending: <Clock size={14} color="var(--warning)" />,
  parsing: <RefreshCw size={14} color="var(--accent-primary)" />,
  parsed: <CheckCircle size={14} color="var(--success)" />,
  failed: <AlertCircle size={14} color="var(--danger)" />,
}
const PARSE_LABEL_KEYS: Record<string, string> = {
  pending: 'parsePending', parsing: 'parseParsing', parsed: 'parseParsed', failed: 'parseFailed',
}

const PAGE_SIZE = 10
const PARSE_KNOWLEDGE_TYPES = new Set(['prompt_template', 'agent_strategy'])
const ACTIVE_AGENT_STATUSES = new Set(['queued', 'processing'])

const normalizeDocTypeId = (value: string) => (
  value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60).replace(/_+$/g, '')
)

export default function DocumentsPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const [docType, setDocType] = useState('evidence')
  const [catFilter, setCatFilter] = useState('')
  const [uploading, setUploading] = useState(false)
  const [showTypeSettings, setShowTypeSettings] = useState(false)
  const [docTypeDrafts, setDocTypeDrafts] = useState<DocTypeOption[]>([])
  const [savingTypes, setSavingTypes] = useState(false)
  const [sortBy, setSortBy] = useState<'created_at' | 'filename' | 'doc_type'>('created_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [viewMode, setViewMode] = useState<'active' | 'trash'>('active')
  const [confirmAction, setConfirmAction] = useState<{ kind: ConfirmActionKind; id: string; name: string } | null>(null)
  const [confirmPending, setConfirmPending] = useState(false)

  // Parse dialog state
  const [parseDocId, setParseDocId] = useState<string | null>(null)
  const [parseDocName, setParseDocName] = useState('')
  const [parsePrompt, setParsePrompt] = useState('')
  const [parsing, setParsing] = useState(false)
  const [parseKnowledgeSearch, setParseKnowledgeSearch] = useState('')
  const [selectedParseKnowledgeIds, setSelectedParseKnowledgeIds] = useState<string[]>([])

  const { data: docTypesData } = useQuery({
    queryKey: ['document-types'],
    queryFn: () => docsApi.types(),
  })
  const docTypeOptions = useMemo<DocTypeOption[]>(() => {
    const items = docTypesData?.data?.items
    if (!Array.isArray(items) || items.length === 0) return DEFAULT_DOC_TYPES
    return items.map((item: any) => ({
      id: String(item.id),
      label: String(item.label || item.id),
      icon: String(item.icon || '📄'),
      enabled: item.enabled !== false,
      builtin: item.builtin === true,
    }))
  }, [docTypesData])
  const enabledDocTypeOptions = useMemo(
    () => docTypeOptions.filter(item => item.enabled !== false),
    [docTypeOptions],
  )
  const docTypeOptionMap = useMemo(
    () => new Map(docTypeOptions.map(item => [item.id, item])),
    [docTypeOptions],
  )
  const docTypeLabel = (type: string, withIcon = false) => {
    const option = docTypeOptionMap.get(type)
    const meta = DOC_TYPE_META[type]
    const defaultOption = DEFAULT_DOC_TYPES.find(item => item.id === type)
    const label = option && (!option.builtin || !meta || option.label !== defaultOption?.label)
      ? option.label
      : (meta ? t(meta.labelKey) : option?.label || type)
    const icon = option?.icon || meta?.icon || '📄'
    return withIcon ? `${icon} ${label}` : label
  }
  const renderDocTypeIcon = (type: string) => (
    DOC_TYPE_ICONS[type] || (
      <span style={{ width: 16, display: 'inline-flex', justifyContent: 'center', color: 'var(--text-muted)' }}>
        {docTypeOptionMap.get(type)?.icon || DOC_TYPE_META[type]?.icon || '📄'}
      </span>
    )
  )

  useEffect(() => {
    if (enabledDocTypeOptions.length > 0 && !enabledDocTypeOptions.some(item => item.id === docType)) {
      setDocType(enabledDocTypeOptions[0].id)
    }
  }, [docType, enabledDocTypeOptions])

  // Fetch all knowledge items when the parse modal is open.
  const { data: kbAllData } = useQuery({
    queryKey: ['knowledge', 'all'],
    queryFn: () => knowledgeApi.list(),
    enabled: Boolean(parseDocId),
  })
  const allKnowledge: any[] = kbAllData?.data ?? []
  const parseKnowledgePool = allKnowledge.filter(item => PARSE_KNOWLEDGE_TYPES.has(item.item_type))
  const parseKnowledgeItems = parseKnowledgePool.filter(item => {
    const term = parseKnowledgeSearch.trim().toLowerCase()
    if (!term) return true
    return `${item.title} ${(item.tags || []).join(' ')}`.toLowerCase().includes(term)
  })

  const { data, isLoading } = useQuery({
    queryKey: ['docs', caseId, 'active'],
    queryFn: () => docsApi.list(caseId!),
  })
  const allDocs: any[] = data?.data ?? []

  const { data: agentTasksData } = useQuery({
    queryKey: ['agentTasks', caseId, 'documents'],
    queryFn: () => draftsApi.agentTasks(caseId!, { sort_order: 'desc' }),
    enabled: Boolean(caseId),
    refetchInterval: 5_000,
  })
  const agentTasks: AgentTask[] = agentTasksData?.data ?? []
  const parseAgentTasks = agentTasks.filter(task => task.task_type === 'fact_extract' || task.task_type === 'fact_reparse')
  const runningParseDocIds = useMemo(() => new Set(
    agentTasks
      .filter(task => task.task_type === 'fact_extract' && ACTIVE_AGENT_STATUSES.has(task.status))
      .map(task => task.input_params?.document_id)
      .filter(Boolean)
      .map(String),
  ), [agentTasks])
  const parseTaskSignature = parseAgentTasks.map(task => `${task.id}:${task.status}:${task.updated_at}`).join('|')

  useEffect(() => {
    if (!caseId || !parseAgentTasks.some(task => task.status === 'completed' || task.status === 'failed')) return
    qc.invalidateQueries({ queryKey: ['docs', caseId] })
    qc.invalidateQueries({ queryKey: ['facts', caseId] })
  }, [caseId, parseTaskSignature, qc])

  const { data: trashData } = useQuery({
    queryKey: ['docs', caseId, 'trash'],
    queryFn: () => docsApi.trash(caseId!),
    enabled: viewMode === 'trash',
  })
  const trashDocs: any[] = trashData?.data ?? []

  const displayDocs = viewMode === 'active'
    ? (catFilter ? allDocs.filter(d => d.doc_type === catFilter) : allDocs)
    : trashDocs

  const sortedDocs = [...displayDocs].sort((a, b) => {
    const av = a[sortBy] ?? '', bv = b[sortBy] ?? ''
    return sortOrder === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
  })
  const totalPages = Math.max(1, Math.ceil(sortedDocs.length / PAGE_SIZE))
  const docs = sortedDocs.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const groupedByType = allDocs.reduce<Record<string, any[]>>((acc, d) => {
    const key = d.doc_type || 'other'
    if (!acc[key]) acc[key] = []
    acc[key].push(d)
    return acc
  }, {})

  // Upload — no auto-parse
  const onDrop = useCallback(async (accepted: File[]) => {
    if (!accepted.length) return
    setUploading(true)
    try {
      for (const file of accepted) {
        await docsApi.upload(caseId!, file, docType)
        toast.success(`${file.name} 上传成功，请手动触发解析`)
      }
      qc.invalidateQueries({ queryKey: ['docs', caseId] })
    } catch {
      toast.error('上传失败')
    } finally {
      setUploading(false)
    }
  }, [caseId, docType, qc])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, multiple: true })

  const openTypeSettings = () => {
    setDocTypeDrafts(docTypeOptions.map(item => ({ ...item, enabled: item.enabled !== false })))
    setShowTypeSettings(true)
  }

  const updateTypeDraft = (id: string, patch: Partial<DocTypeOption>) => {
    setDocTypeDrafts(prev => prev.map(item => item.id === id ? { ...item, ...patch } : item))
  }

  const addTypeDraft = () => {
    setDocTypeDrafts(prev => ([
      ...prev,
      {
        id: `custom_${Date.now()}`,
        label: t('customType'),
        icon: '📄',
        enabled: true,
        builtin: false,
      },
    ]))
  }

  const removeTypeDraft = (id: string) => {
    setDocTypeDrafts(prev => prev.filter(item => item.id !== id))
  }

  const saveDocumentTypes = async () => {
    const cleaned = docTypeDrafts.map(item => ({
      id: normalizeDocTypeId(item.id || item.label),
      label: (item.label || item.id).trim() || item.id,
      icon: (item.icon || '📄').trim() || '📄',
      enabled: item.enabled !== false,
      builtin: item.builtin === true,
    })).filter(item => item.id)

    if (!cleaned.some(item => item.enabled)) {
      toast.error(t('documentTypesNeedOne'))
      return
    }

    setSavingTypes(true)
    try {
      await docsApi.updateTypes(cleaned)
      toast.success(t('documentTypesSaved'))
      qc.invalidateQueries({ queryKey: ['document-types'] })
      setShowTypeSettings(false)
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || t('error'))
    } finally {
      setSavingTypes(false)
    }
  }

  // Open parse dialog
  const openParseDialog = (docId: string, docName: string) => {
    if (runningParseDocIds.has(docId)) {
      toast.error(t('parseTaskAlreadyRunning'))
      return
    }
    setParseDocId(docId)
    setParseDocName(docName)
    setParsePrompt('')
    setParseKnowledgeSearch('')
    setSelectedParseKnowledgeIds([])
  }

  // Trigger parse with prompt
  const handleParse = async () => {
    if (!parseDocId) return
    if (runningParseDocIds.has(parseDocId)) {
      toast.error(t('parseTaskAlreadyRunning'))
      setParseDocId(null)
      return
    }
    setParsing(true)
    try {
      const selectedKnowledge = parseKnowledgePool.filter(item => selectedParseKnowledgeIds.includes(item.id))
      const knowledgePrompt = selectedKnowledge.length > 0
        ? [
          t('selectedParseKnowledgePromptPrefix'),
          selectedKnowledge.map((item, index) => (
            `【${index + 1}. ${item.title} / ${knowledgeTypeLabel(item.item_type)}】\n${item.content}`
          )).join('\n\n'),
        ].join('\n\n')
        : ''
      const promptForParse = [parsePrompt.trim(), knowledgePrompt].filter(Boolean).join('\n\n')
      const res = await docsApi.triggerParse(parseDocId, promptForParse || undefined)
      const promptInfo = promptForParse ? `（使用提示词）` : ''
      toast.success(res.data.message || `${t('parseQueued')}${promptInfo}`)
      qc.invalidateQueries({ queryKey: ['docs', caseId] })
      qc.invalidateQueries({ queryKey: ['facts', caseId] })
      qc.invalidateQueries({ queryKey: ['agentTasks', caseId] })
      setParseDocId(null)
    } catch (e: any) {
      toast.error(`${readableLlmError(e, i18n.language, 'parse')}：${parseDocName}`)
    }
    finally { setParsing(false) }
  }

  const appendParseGuidance = (content: string) => {
    setParsePrompt(prev => prev ? `${prev}\n- ${content}` : `- ${content}`)
  }

  const toggleParseKnowledge = (id: string) => {
    setSelectedParseKnowledgeIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const knowledgeTypeLabel = (type: string) => ({
    prompt_template: t('promptTemplateShort'),
    document_template: t('documentTemplateShort'),
    sample_document: t('sampleDocumentShort'),
    agent_strategy: t('agentStrategyShort'),
  }[type] || t('itemKnowledge'))

  const deleteDoc = async (docId: string) => {
    try {
      await docsApi.softDelete(docId)
      toast.success(t('movedToTrash'))
      qc.invalidateQueries({ queryKey: ['docs', caseId] })
    } catch { toast.error('删除失败') }
  }

  const restoreDoc = async (docId: string) => {
    try {
      await docsApi.restore(docId)
      toast.success('已恢复')
      qc.invalidateQueries({ queryKey: ['docs', caseId] })
    } catch { toast.error('恢复失败') }
  }

  const permanentDeleteDoc = async (docId: string) => {
    try {
      await docsApi.permanentDelete(docId)
      toast.success('已彻底删除')
      qc.invalidateQueries({ queryKey: ['docs', caseId] })
    } catch { toast.error('删除失败') }
  }

  const confirmDocumentAction = async () => {
    if (!confirmAction) return
    setConfirmPending(true)
    try {
      if (confirmAction.kind === 'trash') await deleteDoc(confirmAction.id)
      else await permanentDeleteDoc(confirmAction.id)
      setConfirmAction(null)
    } finally {
      setConfirmPending(false)
    }
  }

  const filenameFromDisposition = (disposition: string | undefined, fallback: string) => {
    if (!disposition) return fallback
    const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
    if (utf8Name) {
      try { return decodeURIComponent(utf8Name) } catch { return fallback }
    }
    const asciiName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
    return asciiName || fallback
  }

  const saveBlob = (data: BlobPart, filename: string, contentType?: string) => {
    const blob = new Blob([data], { type: contentType || 'application/octet-stream' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const exportDocText = async (docId: string, filename: string) => {
    try {
      const res = await docsApi.exportText(docId, 'txt')
      const downloadName = filenameFromDisposition(
        res.headers['content-disposition'],
        `${filename.replace(/\.[^.]+$/, '')}_parsed.txt`,
      )
      const contentType = typeof res.headers['content-type'] === 'string' ? res.headers['content-type'] : undefined
      saveBlob(res.data, downloadName, contentType)
      toast.success(t('exportedParsedText', { name: filename }))
    } catch {
      toast.error(t('exportFailed'))
    }
  }

  const downloadDoc = async (docId: string, filename: string) => {
    try {
      const res = await docsApi.download(docId)
      const downloadName = filenameFromDisposition(res.headers['content-disposition'], filename)
      const contentType = typeof res.headers['content-type'] === 'string' ? res.headers['content-type'] : undefined
      saveBlob(res.data, downloadName, contentType)
      toast.success(t('downloadedFile', { name: downloadName }))
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      toast.error(detail || t('downloadFailed'))
    }
  }

  const toggleSort = (field: typeof sortBy) => {
    if (sortBy === field) setSortOrder(o => o === 'asc' ? 'desc' : 'asc')
    else { setSortBy(field); setSortOrder('desc') }
  }
  const sortIndicator = (field: string) => sortBy === field ? (sortOrder === 'asc' ? ' ↑' : ' ↓') : ''
  const renderParseDiagnostics = (doc: any) => {
    const coverage = doc.extracted_metadata?.diagnostics?.coverage
    if (!coverage) return null
    const score = Math.round((coverage.coverage_score ?? 0) * 100)
    const gapCount = coverage.potential_gap_count ?? 0
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
        <span className={`badge ${score >= 75 ? 'badge-green' : 'badge-yellow'}`} style={{ fontSize: '0.68rem' }}>
          {t('parseCoverageSummary', { score, count: coverage.fact_count ?? 0 })}
        </span>
        {gapCount > 0 && (
          <span className="badge badge-yellow" style={{ fontSize: '0.68rem' }}>
            {t('parseCoveragePotentialGaps', { count: gapCount })}
          </span>
        )}
        {(coverage.candidate_signal_count ?? 0) > 0 && (
          <span className="badge badge-gray" style={{ fontSize: '0.68rem' }}>
            {t('parseCoverageSignals', { count: coverage.candidate_signal_count })}
          </span>
        )}
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>📁 {t('documents')}</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={`btn btn-sm ${viewMode === 'active' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => { setViewMode('active'); setPage(1) }}>
            <FolderOpen size={14} /> {t('docTab')}
          </button>
          <button className={`btn btn-sm ${viewMode === 'trash' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => { setViewMode('trash'); setPage(1) }}>
            <Archive size={14} /> {t('trash')}
          </button>
        </div>
      </div>

      {/* Upload area */}
      {viewMode === 'active' && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header">
            <span style={{ fontWeight: 600 }}>{t('uploadDocuments')}</span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <select className="form-select" style={{ width: 220 }} value={docType} onChange={e => setDocType(e.target.value)}>
                {enabledDocTypeOptions.map(type => <option key={type.id} value={type.id}>{docTypeLabel(type.id, true)}</option>)}
              </select>
              <button className="btn btn-ghost btn-sm" onClick={openTypeSettings} title={t('documentTypeSettings')}>
                <Settings size={14} /> {t('documentTypeSettings')}
              </button>
            </div>
          </div>
          <div className="card-body">
            <div {...getRootProps()} className={`dropzone ${isDragActive ? 'active' : ''}`}>
              <input {...getInputProps()} />
              {uploading ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
                  <span className="spinner" />
                  <span style={{ color: 'var(--text-secondary)' }}>{t('uploading')}</span>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
                  <Upload size={32} color={isDragActive ? 'var(--accent-primary)' : 'var(--text-muted)'} />
                  <div style={{ color: isDragActive ? 'var(--accent-primary)' : 'var(--text-secondary)' }}>
                    {t('dropzone')}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{t('dropzoneHint')}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Category filter */}
      {viewMode === 'active' && Object.keys(groupedByType).length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          <button className={`btn btn-sm ${catFilter === '' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => { setCatFilter(''); setPage(1) }}>
            <FolderOpen size={14} /> {t('all')} ({allDocs.length})
          </button>
          {Object.entries(groupedByType).map(([type, items]) => (
            <button key={type} className={`btn btn-sm ${catFilter === type ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => { setCatFilter(type); setPage(1) }}>
              {renderDocTypeIcon(type)} {docTypeLabel(type)} ({items.length})
            </button>
          ))}
        </div>
      )}

      {/* File list */}
      <div className="card">
        {isLoading ? (
          <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
        ) : docs.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
            <File size={40} style={{ marginBottom: 12, opacity: 0.4 }} />
            <div>{viewMode === 'trash' ? t('emptyTrash') : t('noFiles')}</div>
          </div>
        ) : (
          <>
            <div className="document-table-scroll">
              <table className="table document-table">
                <colgroup>
                  <col className="document-file-col" />
                  <col className="document-type-col" />
                  <col className="document-status-col" />
                  <col className="document-time-col" />
                  <col className="document-actions-col" />
                </colgroup>
                <thead>
                  <tr>
                    <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('filename')}>{t('filename')}{sortIndicator('filename')}</th>
                    <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('doc_type')}>{t('type')}{sortIndicator('doc_type')}</th>
                    <th>{t('parseStatus')}</th>
                    <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('created_at')}>{t('time')}{sortIndicator('created_at')}</th>
                    <th>{t('actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {docs.map((d: any) => {
                    const isParseRunning = d.parse_status === 'parsing' || runningParseDocIds.has(d.id)
                    return (
                    <tr key={d.id}>
                      <td>
                        <div className="document-file-name" title={d.filename}>
                          {renderDocTypeIcon(d.doc_type)}
                          <span>{d.filename}</span>
                        </div>
                      </td>
                      <td className="document-type-cell"><span className="badge badge-blue">{docTypeLabel(d.doc_type)}</span></td>
                      <td>
                        <div className="document-parse-status">
                          {PARSE_STATUS_ICONS[d.parse_status]}
                          <span>{PARSE_LABEL_KEYS[d.parse_status] ? t(PARSE_LABEL_KEYS[d.parse_status]) : d.parse_status}</span>
                        </div>
                        {renderParseDiagnostics(d)}
                      </td>
                      <td className="document-time-cell">
                        <div>{t('updatedAt')}: {formatLocalDateTime(d.updated_at || d.created_at, i18n.language)}</div>
                      </td>
                      <td>
                        <div className="document-action-row">
                          {viewMode === 'active' ? (
                            <>
                              <button className="btn btn-ghost btn-sm" onClick={() => openParseDialog(d.id, d.filename)}
                                disabled={isParseRunning}
                                title={isParseRunning ? t('parseTaskAlreadyRunning') : d.parse_status === 'parsed' ? t('reparse') : t('aiParse')}>
                                {isParseRunning ? <span className="spinner" /> : <Wand2 size={13} />}
                                {isParseRunning ? t('parseParsing') : d.parse_status === 'parsed' ? t('reparse') : t('parse')}
                              </button>
                              <button className="btn btn-ghost btn-sm" onClick={() => downloadDoc(d.id, d.filename)}
                                disabled={(d.file_size ?? 0) <= 0}
                                title={(d.file_size ?? 0) <= 0 ? t('fileEmptyReupload') : t('downloadOriginal')}>
                                <Download size={13} /> {t('originalFile')}
                              </button>
                              <button className="btn btn-ghost btn-sm" onClick={() => exportDocText(d.id, d.filename)}
                                title={t('exportParsedText')}>
                                <FileText size={13} /> {t('parsedText')}
                              </button>
                              <ObjectLifecycleActions
                                mode="active"
                                onTrash={() => setConfirmAction({ kind: 'trash', id: d.id, name: d.filename })}
                                onRestore={() => restoreDoc(d.id)}
                                onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: d.id, name: d.filename })}
                              />
                            </>
                          ) : (
                            <ObjectLifecycleActions
                              mode="trash"
                              onTrash={() => setConfirmAction({ kind: 'trash', id: d.id, name: d.filename })}
                              onRestore={() => restoreDoc(d.id)}
                              onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: d.id, name: d.filename })}
                            />
                          )}
                        </div>
                      </td>
                    </tr>
                  )})}
                </tbody>
              </table>
            </div>

            {/* Pagination — always visible */}
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8, padding: '12px 0', borderTop: '1px solid var(--border)' }}>
              <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                <ChevronLeft size={14} /> 上一页
              </button>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                第 {page} 页 / 共 {totalPages} 页（{sortedDocs.length} 条）
              </span>
              <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                下一页 <ChevronRight size={14} />
              </button>
            </div>
          </>
        )}
      </div>

      {/* Document Type Settings Modal */}
      {showTypeSettings && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(0,0,0,0.7)', padding: 16,
        }} onClick={() => !savingTypes && setShowTypeSettings(false)}>
          <div className="card fade-up" style={{ width: 720, maxWidth: '100%', maxHeight: '85vh', overflow: 'auto', padding: 28 }}
            onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Settings size={18} /> {t('documentTypeSettings')}
              </h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowTypeSettings(false)} disabled={savingTypes} title={t('cancel')}>
                <X size={16} />
              </button>
            </div>

            <div style={{ display: 'grid', gap: 8 }}>
              {docTypeDrafts.map(item => (
                <div
                  key={item.id}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '36px 62px minmax(0, 1fr) 78px 36px',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={item.enabled !== false}
                    onChange={e => updateTypeDraft(item.id, { enabled: e.target.checked })}
                    title={t('enabled')}
                    style={{ accentColor: 'var(--accent-primary)', justifySelf: 'center' }}
                  />
                  <input
                    className="form-input"
                    value={item.icon || ''}
                    onChange={e => updateTypeDraft(item.id, { icon: e.target.value })}
                    placeholder="📄"
                    title={t('documentTypeIcon')}
                    style={{ textAlign: 'center', padding: '8px 6px' }}
                  />
                  <input
                    className="form-input"
                    value={item.label}
                    onChange={e => updateTypeDraft(item.id, { label: e.target.value })}
                    placeholder={t('documentTypeName')}
                  />
                  <span className="badge badge-gray" style={{ justifySelf: 'start' }}>
                    {item.builtin ? t('builtinType') : t('customType')}
                  </span>
                  {item.builtin ? (
                    <span />
                  ) : (
                    <button className="btn btn-ghost btn-sm" onClick={() => removeTypeDraft(item.id)} title={t('delete')}>
                      <X size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginTop: 22 }}>
              <button className="btn btn-ghost" onClick={addTypeDraft}>
                <Plus size={16} /> {t('addDocumentType')}
              </button>
              <div style={{ display: 'flex', gap: 10 }}>
                <button className="btn btn-ghost" onClick={() => setShowTypeSettings(false)} disabled={savingTypes}>
                  {t('cancel')}
                </button>
                <button className="btn btn-primary" onClick={saveDocumentTypes} disabled={savingTypes}>
                  {savingTypes ? <span className="spinner" /> : <Save size={16} />}
                  {t('save')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Parse Dialog Modal */}
      {parseDocId && (
        <AiWorkModal
          icon={<Wand2 size={18} />}
          title={t('aiParse')}
          subtitle={parseDocName}
          onClose={() => setParseDocId(null)}
          closeDisabled={parsing}
          closeTitle={t('close')}
        >
            <div className="form-group ai-work-modal-section">
              <label className="form-label">{t('parsePromptOptional')}</label>
              <textarea
                className="form-textarea"
                rows={7}
                value={parsePrompt}
                onChange={e => setParsePrompt(e.target.value)}
                placeholder={t('parsePromptPlaceholder')}
                style={{ width: '100%' }}
              />
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {t('parsePromptHint')}
              </span>
            </div>

            <div className="form-group ai-work-modal-section">
              <label className="form-label">{t('lawyerAgentGuidance')}</label>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {t('lawyerAgentGuidanceHint')}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
                {['guidanceFocusImpact', 'guidanceFocusDates', 'guidanceFocusContradictions', 'guidanceFocusCriteria'].map(key => (
                  <button key={key} className="btn btn-sm btn-ghost" onClick={() => appendParseGuidance(t(key))}>
                    {t(key)}
                  </button>
                ))}
              </div>
            </div>

            <div className="form-group ai-work-modal-section">
              <label className="form-label">
                <BookOpen size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
                {t('knowledgeReferenceOptional')}
              </label>
              <div style={{ position: 'relative', marginBottom: 8 }}>
                <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input
                  className="form-input"
                  value={parseKnowledgeSearch}
                  onChange={e => setParseKnowledgeSearch(e.target.value)}
                  placeholder={t('knowledgeSearchPlaceholder')}
                  style={{ height: 34, paddingLeft: 34 }}
                />
              </div>
              <div className="ai-work-modal-scroll-list">
                {parseKnowledgePool.length === 0 ? (
                  <div style={{ padding: 14, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    {t('emptyParseKnowledge')}
                  </div>
                ) : parseKnowledgeItems.length === 0 ? (
                  <div style={{ padding: 14, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    {t('noKnowledgeMatches')}
                  </div>
                ) : parseKnowledgeItems.map((ki: any) => (
                  <label
                    key={ki.id}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
                      borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                      background: selectedParseKnowledgeIds.includes(ki.id) ? 'rgba(79,142,247,0.1)' : 'transparent',
                      border: selectedParseKnowledgeIds.includes(ki.id) ? '1px solid rgba(79,142,247,0.3)' : '1px solid transparent',
                    }}
                  >
                    <input type="checkbox" checked={selectedParseKnowledgeIds.includes(ki.id)}
                      onChange={() => toggleParseKnowledge(ki.id)}
                      style={{ accentColor: 'var(--accent-primary)' }} />
                    <span>{TYPE_ICONS[ki.item_type] || '📄'}</span>
                    <span style={{ fontSize: '0.875rem' }}>{ki.title}</span>
                    <span className="badge badge-gray" style={{ fontSize: '0.7rem', marginLeft: 'auto' }}>
                      {knowledgeTypeLabel(ki.item_type)}
                    </span>
                  </label>
                ))}
              </div>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
                {t('selectedKnowledgeParseHint', { count: selectedParseKnowledgeIds.length })}
              </span>
            </div>

            <div className="ai-work-modal-actions">
              <button className="btn btn-ghost" onClick={() => setParseDocId(null)} disabled={parsing}>{t('cancel')}</button>
              <button className="btn btn-primary" onClick={handleParse} disabled={parsing}>
                {parsing ? <span className="spinner" /> : <Wand2 size={16} />}
                {parsing ? t('parseParsing') : t('parse')}
              </button>
            </div>
        </AiWorkModal>
      )}

      {confirmAction && (
        <ConfirmActionModal
          action={confirmAction.kind}
          itemName={confirmAction.name}
          itemType={t('itemDocument')}
          isPending={confirmPending}
          onCancel={() => setConfirmAction(null)}
          onConfirm={confirmDocumentAction}
        />
      )}
    </div>
  )
}
