import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  Wand2, RefreshCw, Clock, CheckCircle, ChevronDown, ChevronUp,
  Edit3, Trash2, BookOpen, Archive,
  Download, ChevronLeft, ChevronRight, Languages, History, Search, ArrowUpDown
} from 'lucide-react'
import { draftsApi, sessionsApi, knowledgeApi, factsApi, translateApi } from '../api'
import { useCaseWebSocket } from '../hooks/useWebSocket'
import { ConfirmActionKind, ConfirmActionModal, ObjectLifecycleActions } from '../components/ObjectLifecycleActions'
import { formatLocalDateTime } from '../utils/time'
import { readableLlmError } from '../utils/llmError'

type Section = {
  id: string; version: string; section_order: number;
  section_title: string; content_preview: string; content?: string; status: string;
  created_at?: string | null; updated_at?: string | null;
}
type AgentTask = { id: string; task_type: string; status: string; created_at?: string | null; updated_at?: string | null }
type KnowledgeItem = { id: string; title: string; item_type: string; content: string }
type FactItem = { id: string; category: string; content: string; status: string; confidence_score: number }
type DraftRevision = {
  id: string; revision_number: number; section_title: string; content_preview: string; content: string;
  editor_role: string; change_summary: string; created_at?: string;
}

const STRATEGY_OPTIONS = [
  { value: 'strongest_first', labelKey: 'strategyStrongestFirst' },
  { value: 'conservative', labelKey: 'strategyConservative' },
  { value: 'narrative', labelKey: 'strategyNarrative' },
  { value: 'criterion', labelKey: 'strategyCriterion' },
]

const PAGE_SIZE = 5
const sectionStatusLabelKey: Record<string, string> = {
  draft: 'sectionStatusDraft',
  approved: 'sectionStatusApproved',
  locked: 'sectionStatusLocked',
}

const agentTaskTypeLabelKey: Record<string, string> = {
  draft_generate: 'agentTaskDraftGenerate',
  rewrite_section: 'agentTaskRewriteSection',
  rfi_generate: 'agentTaskRfiGenerate',
  fact_extract: 'agentTaskFactExtract',
  merge: 'agentTaskMerge',
  translate: 'agentTaskTranslate',
}

const agentTaskStatusLabelKey: Record<string, string> = {
  queued: 'agentTaskQueued',
  processing: 'agentTaskProcessing',
  completed: 'agentTaskCompleted',
  failed: 'agentTaskFailed',
  cancelled: 'agentTaskCancelled',
}

export default function DraftsPage() {
  const { caseId } = useParams<{ caseId: string }>()
  useCaseWebSocket(caseId!)

  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editId, setEditId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [showGenModal, setShowGenModal] = useState(false)
  const [viewMode, setViewMode] = useState<'active' | 'trash'>('active')
  const [page, setPage] = useState(1)
  const [draftExporting, setDraftExporting] = useState(false)
  const [confirmAction, setConfirmAction] = useState<{ kind: ConfirmActionKind; id: string; name: string } | null>(null)
  const [confirmPending, setConfirmPending] = useState(false)
  const [translateTarget, setTranslateTarget] = useState<'en' | 'zh'>('en')
  const [translatingId, setTranslatingId] = useState<string | null>(null)
  const [translationDraft, setTranslationDraft] = useState<{ id: string; title: string; original: string; content: string } | null>(null)
  const [historySection, setHistorySection] = useState<Section | null>(null)
  const [draftSortOrder, setDraftSortOrder] = useState<'asc' | 'desc'>('desc')
  const saveTimer = useRef<ReturnType<typeof setTimeout>>()

  // Prompt-based generation
  const [genTitle, setGenTitle] = useState('')
  const [genPrompt, setGenPrompt] = useState('')
  const [genStrategy, setGenStrategy] = useState('strongest_first')
  const [selectedKnowledgeIds, setSelectedKnowledgeIds] = useState<string[]>([])
  const [selectedFactIds, setSelectedFactIds] = useState<string[]>([])
  const [genKnowledgeSearch, setGenKnowledgeSearch] = useState('')

  // Rewrite modal state
  const [showRewriteModal, setShowRewriteModal] = useState(false)
  const [rewriteSectionId, setRewriteSectionId] = useState<string | null>(null)
  const [rewriteInstruction, setRewriteInstruction] = useState('')
  const [rewriteStrategy, setRewriteStrategy] = useState('strongest_first')
  const [rewriteFactIds, setRewriteFactIds] = useState<string[]>([])
  const [rewriteKnowledgeIds, setRewriteKnowledgeIds] = useState<string[]>([])
  const [rewriteKnowledgeSearch, setRewriteKnowledgeSearch] = useState('')

  // Reset page on view mode change
  useEffect(() => { setPage(1) }, [viewMode, draftSortOrder])

  const { data: sectionsData, isLoading: sectionsLoading } = useQuery({
    queryKey: ['drafts', caseId, draftSortOrder],
    queryFn: () => draftsApi.list(caseId!, undefined, { sort_by: 'updated_at', sort_order: draftSortOrder }),
    refetchInterval: 15_000,
  })
  const allSections: Section[] = sectionsData?.data ?? []

  // Trash query
  const { data: trashData, isLoading: trashLoading } = useQuery({
    queryKey: ['drafts-trash', caseId, draftSortOrder],
    queryFn: () => draftsApi.trash(caseId!, undefined, { sort_by: 'updated_at', sort_order: draftSortOrder }),
    enabled: viewMode === 'trash',
  })
  const trashSections: Section[] = trashData?.data ?? []

  const displaySections = [...(viewMode === 'active' ? allSections : trashSections)].sort((a, b) => {
    const av = new Date(a.updated_at || a.created_at || 0).getTime()
    const bv = new Date(b.updated_at || b.created_at || 0).getTime()
    return draftSortOrder === 'asc' ? av - bv : bv - av
  })
  const totalPages = Math.max(1, Math.ceil(displaySections.length / PAGE_SIZE))
  const sections = displaySections.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const { data: tasksData } = useQuery({
    queryKey: ['agentTasks', caseId, draftSortOrder],
    queryFn: () => draftsApi.agentTasks(caseId!, { sort_order: draftSortOrder }),
    refetchInterval: 5_000,
  })
  const agentTasks: AgentTask[] = tasksData?.data ?? []
  const runningTask = agentTasks.find(t => t.status === 'processing' || t.status === 'queued')

  useEffect(() => {
    if (!agentTasks.some(t => t.status === 'processing' || t.status === 'queued')) {
      qc.invalidateQueries({ queryKey: ['drafts', caseId] })
    }
  }, [agentTasks, caseId, qc])

  // Knowledge items for selection
  const { data: knowledgeData } = useQuery({
    queryKey: ['knowledge', 'all'],
    queryFn: () => knowledgeApi.list(),
  })
  const knowledgeItems: KnowledgeItem[] = knowledgeData?.data ?? []
  const filterKnowledgeItems = (term: string) => {
    const normalized = term.trim().toLowerCase()
    if (!normalized) return knowledgeItems
    return knowledgeItems.filter(item => {
      const text = `${item.title} ${item.content} ${item.item_type}`.toLowerCase()
      return text.includes(normalized)
    })
  }
  const generationKnowledgeItems = filterKnowledgeItems(genKnowledgeSearch)
  const rewriteKnowledgeItems = filterKnowledgeItems(rewriteKnowledgeSearch)
  const { data: revisionsData, isLoading: revisionsLoading } = useQuery({
    queryKey: ['draft-revisions', historySection?.id],
    queryFn: () => draftsApi.revisions(historySection!.id),
    enabled: !!historySection,
  })
  const draftRevisions: DraftRevision[] = revisionsData?.data ?? []

  // Facts query for generation
  const { data: factsData } = useQuery({
    queryKey: ['facts', caseId],
    queryFn: () => factsApi.list(caseId!),
  })
  const allFacts: FactItem[] = factsData?.data ?? []
  const approvedFacts = allFacts.filter((f: FactItem) => f.status === 'lawyer_approved')

  const generateMutation = useMutation({
    mutationFn: () => draftsApi.generate(caseId!, genTitle, genPrompt, genStrategy, selectedKnowledgeIds, selectedFactIds),
    onSuccess: (res) => {
      toast.success(res.data.message ?? '文案生成已启动')
      qc.invalidateQueries({ queryKey: ['agentTasks', caseId] })
      qc.invalidateQueries({ queryKey: ['drafts', caseId] })
      setShowGenModal(false); setGenTitle(''); setGenPrompt(''); setGenStrategy('strongest_first'); setSelectedKnowledgeIds([]); setSelectedFactIds([]); setGenKnowledgeSearch('')
    },
    onError: (e: any) => toast.error(readableLlmError(e, i18n.language, 'generate')),
  })

  const rewriteMutation = useMutation({
    mutationFn: ({ sectionId, instr, strategy, factIds, knowledgeIds }: { sectionId: string; instr: string; strategy: string; factIds: string[]; knowledgeIds: string[] }) =>
      draftsApi.rewrite(sectionId, instr, strategy, knowledgeIds, factIds),
    onSuccess: () => {
      toast.success(t('fullDraftRewriteQueued'))
      setShowRewriteModal(false); setRewriteSectionId(null); setRewriteInstruction(''); setRewriteStrategy('strongest_first'); setRewriteFactIds([]); setRewriteKnowledgeIds([]); setRewriteKnowledgeSearch('')
      qc.invalidateQueries({ queryKey: ['agentTasks', caseId] })
    },
    onError: (e: any) => toast.error(readableLlmError(e, i18n.language, 'rewrite')),
  })

  const restoreRevisionMutation = useMutation({
    mutationFn: ({ sectionId, revisionId }: { sectionId: string; revisionId: string }) =>
      draftsApi.restoreRevision(sectionId, revisionId),
    onSuccess: () => {
      toast.success(t('revisionRestored'))
      setHistorySection(null)
      qc.invalidateQueries({ queryKey: ['drafts', caseId] })
    },
    onError: () => toast.error(t('error')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => draftsApi.softDelete(id),
    onSuccess: () => {
      toast.success(t('movedToTrash'))
      qc.invalidateQueries({ queryKey: ['drafts', caseId] })
      qc.invalidateQueries({ queryKey: ['drafts-trash', caseId] })
    },
  })

  const restoreMutation = useMutation({
    mutationFn: (id: string) => draftsApi.restore(id),
    onSuccess: () => {
      toast.success(t('restored'))
      qc.invalidateQueries({ queryKey: ['drafts', caseId] })
      qc.invalidateQueries({ queryKey: ['drafts-trash', caseId] })
    },
  })

  const permanentDeleteMutation = useMutation({
    mutationFn: (id: string) => draftsApi.permanentDelete(id),
    onSuccess: () => {
      toast.success(t('permanentlyDeleted'))
      qc.invalidateQueries({ queryKey: ['drafts-trash', caseId] })
    },
    onError: (e: any) => toast.error(t('deleteFailedWithReason', { reason: e?.response?.data?.detail || e.message })),
  })

  const confirmDraftAction = async () => {
    if (!confirmAction) return
    setConfirmPending(true)
    try {
      if (confirmAction.kind === 'trash') await deleteMutation.mutateAsync(confirmAction.id)
      else await permanentDeleteMutation.mutateAsync(confirmAction.id)
      setConfirmAction(null)
    } finally {
      setConfirmPending(false)
    }
  }

  const updateMutation = useMutation({
    mutationFn: ({ id, title, content }: { id: string; title: string; content: string }) =>
      draftsApi.update(id, { section_title: title.trim(), content_preview: content }),
    onSuccess: () => {
      toast.success('已保存')
      setEditId(null)
      setEditTitle('')
      qc.invalidateQueries({ queryKey: ['drafts', caseId] })
    },
  })

  const handleTranslateSection = async (section: Section, targetLang: 'en' | 'zh') => {
    const original = section.content || section.content_preview
    await translateSectionContent(section.id, section.section_title, original, targetLang)
  }

  const translateSectionContent = async (id: string, title: string, original: string, targetLang: 'en' | 'zh') => {
    if (!original.trim()) {
      toast.error('没有可翻译的内容')
      return
    }

    setTranslatingId(id)
    try {
      const sourceLang = targetLang === 'en' ? 'zh' : 'en'
      const res = await translateApi.translate(original, sourceLang, targetLang)
      setTranslateTarget(targetLang)
      setTranslationDraft({ id, title, original, content: res.data.translated })
    } catch (e: any) {
      toast.error(readableLlmError(e, i18n.language, 'translate'))
    } finally {
      setTranslatingId(null)
    }
  }

  const applyTranslation = async () => {
    if (!translationDraft) return
    await updateMutation.mutateAsync({
      id: translationDraft.id,
      title: translationDraft.title,
      content: translationDraft.content,
    })
    setTranslationDraft(null)
  }

  const autoSave = () => {
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(async () => {
      try { await sessionsApi.save(caseId!, { page: 'drafts' }) } catch { }
    }, 3000)
  }
  useEffect(() => { autoSave() }, [viewMode])

  const taskStatusIcon = (status: string) => ({
    queued: <Clock size={13} color="var(--warning)" />,
    processing: <RefreshCw size={13} color="var(--accent-primary)" className="spin" />,
    completed: <CheckCircle size={13} color="var(--success)" />,
  }[status] ?? <Clock size={13} />)

  const toggleKnowledge = (id: string) => {
    setSelectedKnowledgeIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }
  const toggleFact = (id: string) => {
    setSelectedFactIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }
  const toggleRewriteKnowledge = (id: string) => {
    setRewriteKnowledgeIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }
  const selectAllFacts = () => {
    setSelectedFactIds(allFacts.map(f => f.id))
  }
  const applyGenerationStrategy = (strategy: string, content: string) => {
    setGenStrategy(strategy)
    setGenPrompt(prev => prev ? `${prev}\n- ${content}` : `- ${content}`)
  }
  const applyRewriteStrategy = (strategy: string, content: string) => {
    setRewriteStrategy(strategy)
    setRewriteInstruction(prev => prev ? `${prev}\n- ${content}` : `- ${content}`)
  }

  const TYPE_ICONS: Record<string, string> = { prompt_template: '🧠', document_template: '📋', sample_document: '📄', agent_strategy: '🎯' }
  const knowledgeTypeLabel = (type: string) => ({
    prompt_template: t('promptTemplateShort'),
    document_template: t('documentTemplateShort'),
    sample_document: t('sampleDocumentShort'),
    agent_strategy: t('agentStrategyShort'),
  }[type] || t('itemKnowledge'))

  const filenameFromDisposition = (disposition: string | undefined, fallback: string) => {
    if (!disposition) return fallback
    const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
    if (utf8Name) {
      try { return decodeURIComponent(utf8Name) } catch { return fallback }
    }
    const asciiName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
    return asciiName || fallback
  }

  const saveBlob = (data: BlobPart | Blob, filename: string, contentType?: string) => {
    const blob = data instanceof Blob ? data : new Blob([data], { type: contentType || 'application/octet-stream' })
    if (blob.size === 0) {
      toast.error(t('emptyExport'))
      return false
    }
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    return true
  }

  const errorDetailFromBlob = async (error: any) => {
    const data = error?.response?.data
    if (data instanceof Blob) {
      try {
        const text = await data.text()
        const parsed = JSON.parse(text)
        return parsed?.detail || text
      } catch {
        return '导出失败'
      }
    }
    return error?.response?.data?.detail || '导出失败'
  }

  const handleDraftExport = async (format: 'txt' | 'md' | 'docx' = 'docx') => {
    if (draftExporting) return
    setDraftExporting(true)
    try {
      const res = await draftsApi.exportDrafts(caseId!, undefined, format)
      const contentType = typeof res.headers['content-type'] === 'string' ? res.headers['content-type'] : undefined
      const fallbackName = `draft_MAIN.${format}`
      const downloadName = filenameFromDisposition(res.headers['content-disposition'], fallbackName)
      if (!saveBlob(res.data, downloadName, contentType)) return
      toast.success(t('exportedAllDrafts'))
    } catch (e: any) {
      toast.error(await errorDetailFromBlob(e))
    } finally {
      setDraftExporting(false)
    }
  }

  const handleSectionExport = async (sectionId: string, sectionTitle: string) => {
    try {
      const res = await draftsApi.exportSection(sectionId, 'docx')
      const contentType = typeof res.headers['content-type'] === 'string' ? res.headers['content-type'] : undefined
      const safeTitle = sectionTitle.replace(/[/\\:*?"<>|]/g, '_').substring(0, 30)
      const downloadName = filenameFromDisposition(res.headers['content-disposition'], `${safeTitle}.docx`)
      if (!saveBlob(res.data, downloadName, contentType)) return
      toast.success(`已导出「${sectionTitle}」`)
    } catch (e: any) {
      toast.error(await errorDetailFromBlob(e))
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>✍️ {t('drafts')}</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
            {t('draftDescription')}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className={`btn btn-sm ${viewMode === 'active' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setViewMode('active')}>{t('draftTab')}</button>
          <button className={`btn btn-sm ${viewMode === 'trash' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setViewMode('trash')}>
            <Archive size={14} /> {t('trash')}
          </button>
          {runningTask && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', background: 'rgba(79,142,247,0.1)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(79,142,247,0.2)', fontSize: '0.8rem', color: 'var(--accent-primary)' }}>
              <RefreshCw size={13} /> {t('aiProcessing')}
            </div>
          )}
          <button className="btn btn-ghost" onClick={() => handleDraftExport('docx')} disabled={draftExporting || !!runningTask} title={allSections.length > 0 ? t('downloadCurrentWordTitle') : t('downloadAllDraftsTitle')}>
            {draftExporting ? <span className="spinner" /> : <Download size={16} />} {allSections.length > 0 ? t('downloadCurrent') : t('downloadAll')}
          </button>
          <button className="btn btn-gold" onClick={() => setShowGenModal(true)}>
            <Wand2 size={16} /> {t('generateDrafts')}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {viewMode === 'active' && (
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => setDraftSortOrder(o => o === 'asc' ? 'desc' : 'asc')}>
              <ArrowUpDown size={13} /> {t('updatedAt')}{draftSortOrder === 'asc' ? ' ↑' : ' ↓'}
            </button>
            <span style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--text-muted)', alignSelf: 'center' }}>
              {t('fullDraftCount', { count: allSections.length })}
            </span>
          </>
        )}
      </div>

      {/* Full drafts */}
      {(sectionsLoading || trashLoading) ? (
        <div style={{ padding: 60, textAlign: 'center' }}><span className="spinner" /></div>
      ) : displaySections.length === 0 ? (
        <div className="card" style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)' }}>
          {viewMode === 'trash' ? (
            <>
              <Trash2 size={48} style={{ marginBottom: 16, opacity: 0.4 }} />
              <div>{t('emptyTrash')}</div>
            </>
          ) : (
            <>
              <div style={{ fontSize: '2.5rem', marginBottom: 16 }}>✍️</div>
              <div style={{ marginBottom: 20 }}>{t('noDrafts')}</div>
              <button className="btn btn-gold" onClick={() => setShowGenModal(true)}>
                <Wand2 size={16} /> {t('generateDrafts')}
              </button>
            </>
          )}
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {sections.map((s) => (
              <div key={s.id} className="card" style={{ position: 'relative' }}>
                <div style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                  onClick={() => setExpandedId(expandedId === s.id ? null : s.id)}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className="badge badge-blue" style={{ fontSize: '0.72rem' }}>{t('fullDraft')}</span>
                    <span style={{ fontWeight: 600 }}>{s.section_title}</span>
                    <span className={`badge ${s.status === 'approved' ? 'badge-green' : 'badge-gray'}`}>
                      {sectionStatusLabelKey[s.status] ? t(sectionStatusLabelKey[s.status]) : s.status}
                    </span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      <Clock size={12} /> {t('updatedAt')}: {formatLocalDateTime(s.updated_at, i18n.language)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    {viewMode === 'active' && (
                      <>
                        <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); setEditId(s.id); setEditTitle(s.section_title); setEditContent(s.content || s.content_preview) }}>
                          <Edit3 size={13} /> {t('edit')}
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={(e) => {
                          e.stopPropagation()
                          setRewriteSectionId(s.id); setRewriteInstruction(''); setRewriteStrategy('strongest_first'); setRewriteFactIds([]); setRewriteKnowledgeIds([]); setShowRewriteModal(true)
                        }}>
                          <Wand2 size={13} /> {t('rewrite')}
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); setHistorySection(s) }}>
                          <History size={13} /> {t('history')}
                        </button>
                        <button className="btn btn-ghost btn-sm" disabled={translatingId === s.id}
                          onClick={(e) => { e.stopPropagation(); handleTranslateSection(s, 'en') }}>
                          {translatingId === s.id ? <span className="spinner" /> : <Languages size={13} />} {t('translateDraft')}
                        </button>
                        <button className="btn btn-ghost btn-sm"
                          onClick={(e) => { e.stopPropagation(); handleSectionExport(s.id, s.section_title) }}
                          title={t('exportWord')}>
                          <Download size={13} /> {t('download')}
                        </button>
                        <ObjectLifecycleActions
                          mode="active"
                          stopPropagation
                          onTrash={() => setConfirmAction({ kind: 'trash', id: s.id, name: s.section_title })}
                          onRestore={() => restoreMutation.mutate(s.id)}
                          onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: s.id, name: s.section_title })}
                        />
                      </>
                    )}
                    {viewMode === 'trash' && (
                      <ObjectLifecycleActions
                        mode="trash"
                        stopPropagation
                        onTrash={() => setConfirmAction({ kind: 'trash', id: s.id, name: s.section_title })}
                        onRestore={() => restoreMutation.mutate(s.id)}
                        onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: s.id, name: s.section_title })}
                      />
                    )}
                    {expandedId === s.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </div>
                </div>

                {expandedId === s.id && (
                  <div style={{ borderTop: '1px solid var(--border)' }}>
                    {editId === s.id ? (
                      <div style={{ padding: '16px 20px' }}>
                        <div className="form-group" style={{ marginBottom: 12 }}>
                          <label className="form-label">{t('title')}</label>
                          <input className="form-input" value={editTitle}
                            onChange={e => setEditTitle(e.target.value)}
                            placeholder={t('enterDraftTitle')} />
                        </div>
                        <label className="form-label">{t('body')}</label>
                        <textarea className="form-textarea" rows={8} value={editContent}
                          onChange={e => setEditContent(e.target.value)} style={{ fontFamily: 'inherit', lineHeight: 1.7 }} />
                        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                          <button className="btn btn-primary btn-sm"
                            disabled={!editTitle.trim() || updateMutation.isPending}
                            onClick={() => updateMutation.mutate({ id: s.id, title: editTitle, content: editContent })}>
                            {t('saveChanges')}
                          </button>
                          <button className="btn btn-ghost btn-sm" onClick={() => { setEditId(null); setEditTitle('') }}>{t('cancel')}</button>
                        </div>
                      </div>
                    ) : (
                      <div className="draft-content-area">{s.content || s.content_preview}</div>
                    )}
                  </div>
                )}

              </div>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{
              display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8,
              padding: '16px 0', marginTop: 12,
            }}>
              <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                <ChevronLeft size={14} /> {t('previousPage')}
              </button>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                {t('pageFullDraftSummary', { page, totalPages, total: displaySections.length })}
              </span>
              <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                {t('nextPage')} <ChevronRight size={14} />
              </button>
            </div>
          )}
        </>
      )}

      {/* Agent tasks */}
      {agentTasks.length > 0 && (
        <div className="card" style={{ marginTop: 24, padding: '16px 20px' }}>
          <div style={{ fontWeight: 600, marginBottom: 12, fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            📋 {t('agentRunLog')}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {agentTasks.slice(0, 5).map(task => (
              <div key={task.id} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.8rem', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                {taskStatusIcon(task.status)}
                <span style={{ color: 'var(--text-secondary)' }}>
                  {agentTaskTypeLabelKey[task.task_type] ? t(agentTaskTypeLabelKey[task.task_type]) : task.task_type}
                </span>
                <span className={`badge ${task.status === 'completed' ? 'badge-green' : task.status === 'failed' ? 'badge-red' : 'badge-gray'}`} style={{ fontSize: '0.68rem' }}>
                  {agentTaskStatusLabelKey[task.status] ? t(agentTaskStatusLabelKey[task.status]) : task.status}
                </span>
                <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>
                  {t('updatedAt')}: {formatLocalDateTime(task.updated_at || task.created_at, i18n.language)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Generate Modal */}
      {showGenModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}>
          <div className="card fade-up" style={{ width: 640, maxHeight: '85vh', overflow: 'auto', padding: 32 }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: 20 }}>
              <Wand2 size={18} style={{ verticalAlign: 'middle', marginRight: 8 }} />
              {t('aiDraftGeneration')}
            </h2>

            <div className="form-group" style={{ marginBottom: 16 }}>
              <label className="form-label">{t('draftTitle')}</label>
              <input className="form-input" value={genTitle} onChange={e => setGenTitle(e.target.value)}
                placeholder={t('draftTitlePlaceholder')} />
            </div>

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">{t('generationInstruction')}</label>
              <textarea className="form-textarea" rows={5} value={genPrompt} onChange={e => setGenPrompt(e.target.value)}
                placeholder={t('generationPlaceholder')} />
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {t('generationHint')}
              </span>
            </div>

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">{t('lawyerStrategy')}</label>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {t('lawyerStrategyHint')}
              </div>
              <div className="form-label" style={{ marginTop: 10 }}>{t('strategyMode')}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                {STRATEGY_OPTIONS.map(option => (
                  <button
                    key={option.value}
                    className={`btn btn-sm ${genStrategy === option.value ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => applyGenerationStrategy(option.value, t(option.labelKey))}
                  >
                    {t(option.labelKey)}
                  </button>
                ))}
              </div>
            </div>

            {/* Fact Selection */}
            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>📋 {t('selectFacts', { total: allFacts.length, approved: approvedFacts.length })}</span>
                <span style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem', color: 'var(--gold)' }}
                    onClick={() => {
                      // AI recommends high-confidence facts as defaults
                      const approvedRecommended = approvedFacts.filter(f => f.confidence_score >= 0.8).map(f => f.id)
                      const recommended = approvedRecommended.length > 0 ? approvedRecommended : allFacts.filter(f => f.confidence_score >= 0.8).map(f => f.id)
                      setSelectedFactIds(recommended.length > 0 ? recommended : allFacts.map(f => f.id))
                      toast.success(t('aiRecommendedFacts', { count: recommended.length || allFacts.length }))
                    }}>🤖 {t('aiRecommend')}</button>
                  <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem' }}
                    onClick={selectAllFacts}>{t('selectAll')}</button>
                  <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem' }}
                    onClick={() => setSelectedFactIds([])}>{t('clear')}</button>
                </span>
              </label>
              {allFacts.length === 0 ? (
                <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                  {t('noFactsForDraft')}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto', padding: 8, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                  {allFacts.map(f => (
                    <label key={f.id} style={{
                      display: 'flex', alignItems: 'flex-start', gap: 10, padding: '6px 10px',
                      borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.82rem',
                      background: selectedFactIds.includes(f.id) ? 'rgba(79,142,247,0.08)' : 'transparent',
                      border: selectedFactIds.includes(f.id) ? '1px solid rgba(79,142,247,0.25)' : '1px solid transparent',
                    }}>
                      <input type="checkbox" checked={selectedFactIds.includes(f.id)}
                        onChange={() => toggleFact(f.id)} style={{ accentColor: 'var(--accent-primary)', marginTop: 2 }} />
                      <span className="badge badge-gray" style={{ fontSize: '0.68rem', flexShrink: 0 }}>{f.category}</span>
                      <span className={`badge ${f.status === 'lawyer_approved' ? 'badge-green' : 'badge-gray'}`} style={{ fontSize: '0.68rem', flexShrink: 0 }}>
                        {f.status === 'lawyer_approved' ? t('confirmed') : t('awaitingClient')}
                      </span>
                      <span style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>{f.content.substring(0, 120)}{f.content.length > 120 ? '…' : ''}</span>
                      {f.confidence_score >= 0.8 && (
                        <span style={{ fontSize: '0.65rem', color: 'var(--gold)', flexShrink: 0 }}>★</span>
                      )}
                    </label>
                  ))}
                </div>
              )}
              <span style={{ fontSize: '0.72rem', color: selectedFactIds.length === 0 ? 'var(--warning)' : 'var(--text-muted)', marginTop: 4, display: 'block' }}>
                {t('factsSelectedSummary', { selected: selectedFactIds.length, total: allFacts.length })}
                {selectedFactIds.length === 0 ? ` ${t('factsRequiredHint')}` : ` ${t('factsWillBeUsed')}`}
              </span>
            </div>

            {knowledgeItems.length > 0 && (
              <div className="form-group" style={{ marginBottom: 20 }}>
                <label className="form-label">
                  <BookOpen size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
                  {t('knowledgeReferenceOptional')}
                </label>
                <div style={{ position: 'relative', marginBottom: 8 }}>
                  <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                  <input
                    className="form-input"
                    value={genKnowledgeSearch}
                    onChange={e => setGenKnowledgeSearch(e.target.value)}
                    placeholder={t('knowledgeSearchPlaceholder')}
                    style={{ height: 34, paddingLeft: 34 }}
                  />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto', padding: 8, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                  {generationKnowledgeItems.length === 0 ? (
                    <div style={{ padding: 14, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                      {t('noKnowledgeMatches')}
                    </div>
                  ) : generationKnowledgeItems.map(ki => (
                    <label key={ki.id} style={{
                      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
                      borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                      background: selectedKnowledgeIds.includes(ki.id) ? 'rgba(79,142,247,0.1)' : 'transparent',
                      border: selectedKnowledgeIds.includes(ki.id) ? '1px solid rgba(79,142,247,0.3)' : '1px solid transparent',
                    }}>
                      <input type="checkbox" checked={selectedKnowledgeIds.includes(ki.id)}
                        onChange={() => toggleKnowledge(ki.id)} style={{ accentColor: 'var(--accent-primary)' }} />
                      <span>{TYPE_ICONS[ki.item_type] || '📄'}</span>
                      <span style={{ fontSize: '0.875rem' }}>{ki.title}</span>
                      <span className="badge badge-gray" style={{ fontSize: '0.7rem', marginLeft: 'auto' }}>
                        {knowledgeTypeLabel(ki.item_type)}
                      </span>
                    </label>
                  ))}
                </div>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
                  {t('selectedKnowledgeGenerationHint', { count: selectedKnowledgeIds.length })}
                </span>
              </div>
            )}

            <div style={{ display: 'flex', gap: 12 }}>
              <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => { setShowGenModal(false); setGenTitle(''); setGenPrompt(''); setGenStrategy('strongest_first'); setSelectedKnowledgeIds([]); setSelectedFactIds([]); setGenKnowledgeSearch('') }}>{t('cancel')}</button>
              <button className="btn btn-gold" style={{ flex: 1 }} onClick={() => generateMutation.mutate()}
                disabled={!genPrompt.trim() || selectedFactIds.length === 0 || generateMutation.isPending}>
                {generateMutation.isPending ? <span className="spinner" /> : <Wand2 size={16} />}
                {t('startGenerate')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Rewrite Modal */}
      {showRewriteModal && rewriteSectionId && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}>
          <div className="card fade-up" style={{ width: 640, maxHeight: '85vh', overflow: 'auto', padding: 32 }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: 20 }}>
              <Wand2 size={18} style={{ verticalAlign: 'middle', marginRight: 8 }} />
              {t('aiFullDraftRewrite')}
              <span style={{ fontSize: '0.8rem', fontWeight: 400, color: 'var(--text-secondary)', marginLeft: 8 }}>
                {displaySections.find(s => s.id === rewriteSectionId)?.section_title}
              </span>
            </h2>

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">{t('rewriteInstructionFull')}</label>
              <textarea className="form-textarea" rows={4} value={rewriteInstruction}
                onChange={e => setRewriteInstruction(e.target.value)}
                placeholder={t('rewriteInstructionPlaceholder')} />
            </div>

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">{t('lawyerStrategy')}</label>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {t('lawyerStrategyHint')}
              </div>
              <div className="form-label" style={{ marginTop: 10 }}>{t('strategyMode')}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                {STRATEGY_OPTIONS.map(option => (
                  <button
                    key={option.value}
                    className={`btn btn-sm ${rewriteStrategy === option.value ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => applyRewriteStrategy(option.value, t(option.labelKey))}
                  >
                    {t(option.labelKey)}
                  </button>
                ))}
              </div>
            </div>

            {/* Fact Selection for Rewrite */}
            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>📋 {t('selectFacts', { total: allFacts.length, approved: approvedFacts.length })}</span>
                <span style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem', color: 'var(--gold)' }}
                    onClick={() => {
                      const approvedRecommended = approvedFacts.filter(f => f.confidence_score >= 0.8).map(f => f.id)
                      const recommended = approvedRecommended.length > 0 ? approvedRecommended : allFacts.filter(f => f.confidence_score >= 0.8).map(f => f.id)
                      setRewriteFactIds(recommended.length > 0 ? recommended : allFacts.map(f => f.id))
                    }}>🤖 {t('aiRecommend')}</button>
                  <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem' }}
                    onClick={() => setRewriteFactIds(allFacts.map(f => f.id))}>{t('selectAll')}</button>
                  <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem' }}
                    onClick={() => setRewriteFactIds([])}>{t('clear')}</button>
                </span>
              </label>
              {allFacts.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 160, overflowY: 'auto', padding: 8, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                  {allFacts.map(f => (
                    <label key={f.id} style={{
                      display: 'flex', alignItems: 'flex-start', gap: 10, padding: '5px 10px',
                      borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: '0.8rem',
                      background: rewriteFactIds.includes(f.id) ? 'rgba(79,142,247,0.08)' : 'transparent',
                    }}>
                      <input type="checkbox" checked={rewriteFactIds.includes(f.id)}
                        onChange={() => setRewriteFactIds(prev => prev.includes(f.id) ? prev.filter(x => x !== f.id) : [...prev, f.id])}
                        style={{ accentColor: 'var(--accent-primary)', marginTop: 2 }} />
                      <span className="badge badge-gray" style={{ fontSize: '0.68rem', flexShrink: 0 }}>{f.category}</span>
                      <span className={`badge ${f.status === 'lawyer_approved' ? 'badge-green' : 'badge-gray'}`} style={{ fontSize: '0.68rem', flexShrink: 0 }}>
                        {f.status === 'lawyer_approved' ? t('confirmed') : t('awaitingClient')}
                      </span>
                      <span style={{ color: 'var(--text-secondary)' }}>{f.content.substring(0, 100)}{f.content.length > 100 ? '…' : ''}</span>
                    </label>
                  ))}
                </div>
              )}
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
                {t('factsOptionalRewriteHint', { selected: rewriteFactIds.length })}
              </span>
            </div>

            {/* Agent style / knowledge references for Rewrite */}
            {knowledgeItems.length > 0 && (
              <div className="form-group" style={{ marginBottom: 20 }}>
                <label className="form-label">
                  <BookOpen size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
                  {t('knowledgeReferenceOptional')}
                </label>
                <div style={{ position: 'relative', marginBottom: 8 }}>
                  <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                  <input
                    className="form-input"
                    value={rewriteKnowledgeSearch}
                    onChange={e => setRewriteKnowledgeSearch(e.target.value)}
                    placeholder={t('knowledgeSearchPlaceholder')}
                    style={{ height: 34, paddingLeft: 34 }}
                  />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto', padding: 8, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                  {rewriteKnowledgeItems.length === 0 ? (
                    <div style={{ padding: 14, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                      {t('noKnowledgeMatches')}
                    </div>
                  ) : rewriteKnowledgeItems.map(ki => (
                    <label key={ki.id} style={{
                      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
                      borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                      background: rewriteKnowledgeIds.includes(ki.id) ? 'rgba(79,142,247,0.1)' : 'transparent',
                      border: rewriteKnowledgeIds.includes(ki.id) ? '1px solid rgba(79,142,247,0.3)' : '1px solid transparent',
                    }}>
                      <input type="checkbox" checked={rewriteKnowledgeIds.includes(ki.id)}
                        onChange={() => toggleRewriteKnowledge(ki.id)}
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
                  {t('selectedKnowledgeRewriteHint', { count: rewriteKnowledgeIds.length })}
                </span>
              </div>
            )}

            <div style={{ display: 'flex', gap: 12 }}>
              <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => { setShowRewriteModal(false); setRewriteSectionId(null); setRewriteStrategy('strongest_first'); setRewriteKnowledgeSearch('') }}>{t('cancel')}</button>
              <button className="btn btn-primary" style={{ flex: 1 }}
                onClick={() => rewriteMutation.mutate({ sectionId: rewriteSectionId, instr: rewriteInstruction, strategy: rewriteStrategy, factIds: rewriteFactIds, knowledgeIds: rewriteKnowledgeIds })}
                disabled={!rewriteInstruction.trim() || rewriteMutation.isPending}>
                {rewriteMutation.isPending ? <span className="spinner" /> : <Wand2 size={16} />}
                {t('startRewrite')}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmAction && (
        <ConfirmActionModal
          action={confirmAction.kind}
          itemName={confirmAction.name}
          itemType="文案"
          isPending={confirmPending}
          onCancel={() => setConfirmAction(null)}
          onConfirm={confirmDraftAction}
        />
      )}

      {translationDraft && (
        <div className="confirm-modal-backdrop" onClick={() => setTranslationDraft(null)}>
          <div className="confirm-modal-card" style={{ width: 'min(720px, calc(100vw - 32px))' }} onClick={(event) => event.stopPropagation()}>
            <div className="confirm-modal-header">
              <span className="confirm-icon"><Languages size={18} /></span>
              <div>
                <h2>{t('translationResult')}</h2>
                <p>{translationDraft.title}</p>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <button className={`btn btn-sm ${translateTarget === 'en' ? 'btn-primary' : 'btn-ghost'}`}
                disabled={translatingId === translationDraft.id}
                onClick={() => translateSectionContent(translationDraft.id, translationDraft.title, translationDraft.original, 'en')}>
                {t('translateToEnglish')}
              </button>
              <button className={`btn btn-sm ${translateTarget === 'zh' ? 'btn-primary' : 'btn-ghost'}`}
                disabled={translatingId === translationDraft.id}
                onClick={() => translateSectionContent(translationDraft.id, translationDraft.title, translationDraft.original, 'zh')}>
                {t('translateToChinese')}
              </button>
            </div>
            <textarea
              className="form-textarea"
              rows={10}
              value={translationDraft.content}
              onChange={(e) => setTranslationDraft({ ...translationDraft, content: e.target.value })}
              style={{ fontFamily: 'inherit', lineHeight: 1.7 }}
            />
            <div className="confirm-modal-actions">
              <button className="btn btn-ghost" onClick={() => setTranslationDraft(null)}>{t('cancel')}</button>
              <button className="btn btn-primary" onClick={applyTranslation} disabled={updateMutation.isPending}>
                {updateMutation.isPending ? <span className="spinner" /> : <CheckCircle size={14} />}
                {t('applyTranslation')}
              </button>
            </div>
          </div>
        </div>
      )}

      {historySection && (
        <div className="confirm-modal-backdrop" onClick={() => setHistorySection(null)}>
          <div className="confirm-modal-card" style={{ width: 'min(820px, calc(100vw - 32px))' }} onClick={(event) => event.stopPropagation()}>
            <div className="confirm-modal-header">
              <span className="confirm-icon"><History size={18} /></span>
              <div>
                <h2>{t('draftHistory')}</h2>
                <p>{historySection.section_title}</p>
              </div>
            </div>
            {revisionsLoading ? (
              <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
            ) : draftRevisions.length === 0 ? (
              <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>{t('noDraftHistory')}</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 460, overflowY: 'auto' }}>
                {draftRevisions.map(revision => (
                  <div key={revision.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 14 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                      <span className="badge badge-blue">#{revision.revision_number}</span>
                      <span className="badge badge-gray">{revision.editor_role}</span>
                      <span style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>{revision.change_summary}</span>
                      <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: '0.76rem' }}>
                        {formatLocalDateTime(revision.created_at, i18n.language)}
                      </span>
                    </div>
                    <div style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.6, maxHeight: 120, overflow: 'auto' }}>
                      {revision.content_preview || t('emptyContent')}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={restoreRevisionMutation.isPending}
                        onClick={() => restoreRevisionMutation.mutate({ sectionId: historySection.id, revisionId: revision.id })}
                      >
                        {restoreRevisionMutation.isPending ? <span className="spinner" /> : <History size={13} />}
                        {t('restoreThisVersion')}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="confirm-modal-actions">
              <button className="btn btn-ghost" onClick={() => setHistorySection(null)}>{t('close')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
