import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  ThumbsUp, ThumbsDown, CheckCircle, Edit3,
  ChevronLeft, ChevronRight, ArrowUpDown, RefreshCw, ClipboardList,
  Archive, Languages, Clock
} from 'lucide-react'
import { factsApi, tasksApi, translateApi } from '../api'
import { ConfirmActionKind, ConfirmActionModal, ObjectLifecycleActions } from '../components/ObjectLifecycleActions'
import { formatLocalDateTime } from '../utils/time'
import { readableLlmError } from '../utils/llmError'

const CAT_COLORS: Record<string, string> = {
  award: '#f0c060', patent: '#60a5fa', publication: '#34d399',
  citation: '#a78bfa', employment: '#fb923c', media: '#f472b6',
  membership: '#2dd4bf', salary: '#facc15', education: '#94a3b8',
  reference_letter: '#c084fc', evidence: '#f87171', other: '#64748b',
  legal_precedent: '#22d3ee', internet_research: '#818cf8',
}

const PAGE_SIZE = 10
type FactSortField = 'updated_at' | 'created_at' | 'category' | 'confidence_score' | 'status'

export default function FactsPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const [disputeId, setDisputeId] = useState<string | null>(null)
  const [disputeComment, setDisputeComment] = useState('')
  const [editId, setEditId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState('')
  const [sortBy, setSortBy] = useState<FactSortField>('updated_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [catFilter, setCatFilter] = useState('')
  const [viewMode, setViewMode] = useState<'active' | 'trash'>('active')
  const [confirmAction, setConfirmAction] = useState<{ kind: ConfirmActionKind; id: string; name: string } | null>(null)
  const [confirmPending, setConfirmPending] = useState(false)
  const [translateTarget, setTranslateTarget] = useState<'en' | 'zh'>('en')
  const [translatingId, setTranslatingId] = useState<string | null>(null)
  const [translationFact, setTranslationFact] = useState<{ id: string; title: string; original: string; content: string } | null>(null)

  // Active facts
  const { data, isLoading } = useQuery({
    queryKey: ['facts', caseId, 'active', sortBy, sortOrder],
    queryFn: () => factsApi.list(caseId!, { sort_by: sortBy, sort_order: sortOrder }),
  })
  const allFacts: any[] = data?.data ?? []

  // Trash facts
  const { data: trashData } = useQuery({
    queryKey: ['facts', caseId, 'trash', sortBy, sortOrder],
    queryFn: () => factsApi.trash(caseId!, { sort_by: sortBy, sort_order: sortOrder }),
    enabled: viewMode === 'trash',
  })
  const trashFacts: any[] = trashData?.data ?? []

  const displayFacts = viewMode === 'active' ? allFacts : trashFacts

  // Filter + Sort + Paginate
  const filtered = catFilter ? displayFacts.filter(f => f.category === catFilter) : displayFacts
  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortBy] ?? '', bv = b[sortBy] ?? ''
    if (typeof av === 'number') return sortOrder === 'asc' ? av - bv : bv - av
    return sortOrder === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
  })
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const facts = sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  // Group categories for filter
  const categories = [...new Set(displayFacts.map(f => f.category))]

  const approveMutation = useMutation({
    mutationFn: (id: string) => factsApi.approve(id),
    onSuccess: (_data, id) => {
      const fact = displayFacts.find(f => f.id === id)
      const wasApproved = fact?.status === 'lawyer_approved'
      toast.success(wasApproved ? t('factUnapproved') : t('confirmed'))
      qc.invalidateQueries({ queryKey: ['facts', caseId] })
    },
  })

  const disputeMutation = useMutation({
    mutationFn: ({ id, comment }: { id: string; comment: string }) => factsApi.dispute(id, comment),
    onSuccess: () => {
      toast.success(t('factDisputeReparsed'))
      qc.invalidateQueries({ queryKey: ['facts', caseId] })
      setDisputeId(null)
      setDisputeComment('')
    },
  })

  const disputeTaskMutation = useMutation({
    mutationFn: async ({ factContent, comment }: { factContent: string; comment: string }) => {
      return tasksApi.create(caseId!, {
        title: `${t('requestEvidence')}: ${comment.substring(0, 50)}`,
        description: `${t('disputeReason')}: ${comment}\n\n${t('relatedFact')}: ${factContent}`,
        task_type: 'document_upload',
      })
    },
    onSuccess: () => {
      toast.success(t('evidenceTaskSubmitted'))
      qc.invalidateQueries({ queryKey: ['tasks', caseId] })
      setDisputeId(null)
      setDisputeComment('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => factsApi.softDelete(id),
    onSuccess: () => { toast.success(t('movedToTrash')); qc.invalidateQueries({ queryKey: ['facts', caseId] }) },
  })

  const restoreMutation = useMutation({
    mutationFn: (id: string) => factsApi.restore(id),
    onSuccess: () => { toast.success(t('restored')); qc.invalidateQueries({ queryKey: ['facts', caseId] }) },
  })

  const permanentDeleteMutation = useMutation({
    mutationFn: (id: string) => factsApi.permanentDelete(id),
    onSuccess: () => { toast.success(t('permanentlyDeleted')); qc.invalidateQueries({ queryKey: ['facts', caseId] }) },
  })

  const confirmFactAction = async () => {
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
    mutationFn: ({ id, content }: { id: string; content: string }) => factsApi.update(id, { content }),
    onSuccess: () => { toast.success(t('saved')); qc.invalidateQueries({ queryKey: ['facts', caseId] }); setEditId(null) },
  })

  const translateFactContent = async (id: string, title: string, original: string, targetLang: 'en' | 'zh') => {
    if (!original.trim()) {
      toast.error(t('nothingToTranslate'))
      return
    }

    setTranslatingId(id)
    try {
      const sourceLang = targetLang === 'en' ? 'zh' : 'en'
      const res = await translateApi.translate(original, sourceLang, targetLang)
      setTranslateTarget(targetLang)
      setTranslationFact({ id, title, original, content: res.data.translated })
    } catch (e: any) {
      toast.error(readableLlmError(e, i18n.language, 'translate'))
    } finally {
      setTranslatingId(null)
    }
  }

  const applyFactTranslation = async () => {
    if (!translationFact) return
    await updateMutation.mutateAsync({
      id: translationFact.id,
      content: translationFact.content,
    })
    setTranslationFact(null)
  }



  const statusBadge = (status: string) => {
    const map: Record<string, [string, string]> = {
      extracted: ['badge-gray', t('awaitingClient')],
      lawyer_approved: ['badge-green', t('confirmed')],
      disputed: ['badge-red', t('dispute')],
    }
    const [cls, label] = map[status] ?? ['badge-gray', status]
    return <span className={`badge ${cls}`}>{label}</span>
  }

  const toggleSort = (field: FactSortField) => {
    if (sortBy === field) setSortOrder(o => o === 'asc' ? 'desc' : 'asc')
    else { setSortBy(field); setSortOrder('desc') }
    setPage(1)
  }
  const sortIndicator = (field: FactSortField) => sortBy === field ? (sortOrder === 'asc' ? ' ↑' : ' ↓') : ''

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>🔍 {t('facts')}</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
            {t('factsDescription', { count: allFacts.length })}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={`btn btn-sm ${viewMode === 'active' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => { setViewMode('active'); setCatFilter(''); setPage(1) }}>
            <CheckCircle size={14} /> {t('facts')}
          </button>
          <button className={`btn btn-sm ${viewMode === 'trash' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => { setViewMode('trash'); setCatFilter(''); setPage(1) }}>
            <Archive size={14} /> {t('trash')}
          </button>
        </div>
      </div>



      {/* Category filter + sort */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <button className={`btn btn-sm ${catFilter === '' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => { setCatFilter(''); setPage(1) }}>{t('all')} ({displayFacts.length})</button>
        {categories.map(cat => (
          <button key={cat} className={`btn btn-sm ${catFilter === cat ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => { setCatFilter(cat); setPage(1) }}
            style={catFilter === cat ? {} : { borderColor: CAT_COLORS[cat] + '40', color: CAT_COLORS[cat] }}>
            {cat} ({displayFacts.filter(f => f.category === cat).length})
          </button>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => toggleSort('updated_at')}>
            <ArrowUpDown size={13} /> {t('updatedAt')}{sortIndicator('updated_at')}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => toggleSort('confidence_score')}>
            <ArrowUpDown size={13} /> {t('confidence')}{sortIndicator('confidence_score')}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => toggleSort('status')}>
            <ArrowUpDown size={13} /> {t('status')}{sortIndicator('status')}
          </button>
        </div>
      </div>

      {isLoading ? (
        <div style={{ padding: 60, textAlign: 'center' }}><span className="spinner" /></div>
      ) : facts.length === 0 ? (
        <div className="card" style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '2rem', marginBottom: 12 }}>{viewMode === 'trash' ? '🗑️' : '📄'}</div>
          <div>{viewMode === 'trash' ? t('emptyTrash') : t('noFactsForDraft')}</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {facts.map((f: any) => (
            <div key={f.id} className="fact-item">
              <div className="fact-category-dot" style={{ background: CAT_COLORS[f.category] ?? '#64748b' }} />
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span className="badge badge-blue" style={{ background: `${CAT_COLORS[f.category]}20`, color: CAT_COLORS[f.category] }}>
                      {f.category}
                    </span>
                    {statusBadge(f.status)}
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {t('confidence')} {Math.round(f.confidence_score * 100)}%
                    </span>
                    {/* Source badges */}
                    {f.structured_data?.source && (
                      <span className="badge badge-yellow" style={{ fontSize: '0.7rem' }}>
                        🔗 {f.structured_data.source}
                      </span>
                    )}
                    {f.structured_data?.document_name && (
                      <span className="badge badge-blue" style={{ fontSize: '0.7rem' }}>
                        📎 {t('source')}: {f.structured_data.document_name}
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {viewMode === 'active' ? (
                      <>

                        <button className="btn btn-ghost btn-sm" onClick={() => { setEditId(f.id); setEditContent(f.content) }}>
                          <Edit3 size={13} />
                        </button>
                        <button className="btn btn-ghost btn-sm" disabled={translatingId === f.id}
                          onClick={() => translateFactContent(f.id, f.category, f.content, 'en')}>
                          {translatingId === f.id ? <span className="spinner" /> : <Languages size={13} />} {t('translate')}
                        </button>
                        <button className={`btn btn-ghost btn-sm ${f.status === 'lawyer_approved' ? 'btn-active' : ''}`}
                          onClick={() => approveMutation.mutate(f.id)}
                          style={f.status === 'lawyer_approved' ? { color: 'var(--success)' } : {}}>
                          <ThumbsUp size={13} /> {f.status === 'lawyer_approved' ? t('confirmed') : t('confirm')}
                        </button>
                        <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }}
                          onClick={() => { setDisputeId(f.id); setDisputeComment('') }}>
                          <ThumbsDown size={13} /> {t('dispute')}
                        </button>
                        <ObjectLifecycleActions
                          mode="active"
                          onTrash={() => setConfirmAction({ kind: 'trash', id: f.id, name: f.content.substring(0, 60) })}
                          onRestore={() => restoreMutation.mutate(f.id)}
                          onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: f.id, name: f.content.substring(0, 60) })}
                        />
                      </>
                    ) : (
                      <ObjectLifecycleActions
                        mode="trash"
                        onTrash={() => setConfirmAction({ kind: 'trash', id: f.id, name: f.content.substring(0, 60) })}
                        onRestore={() => restoreMutation.mutate(f.id)}
                        onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: f.id, name: f.content.substring(0, 60) })}
                      />
                    )}
                  </div>
                </div>

                {/* Content (editable) */}
                {editId === f.id ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <textarea className="form-textarea" rows={3} value={editContent} onChange={e => setEditContent(e.target.value)} />
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button className="btn btn-primary btn-sm" onClick={() => updateMutation.mutate({ id: f.id, content: editContent })}>{t('save')}</button>
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditId(null)}>{t('cancel')}</button>
                    </div>
                  </div>
                ) : (
                  <p style={{ fontSize: '0.9rem', lineHeight: 1.6, color: 'var(--text-primary)' }}>{f.content}</p>
                )}

                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  <Clock size={12} />
                  <span>{t('updatedAt')}: {formatLocalDateTime(f.updated_at, i18n.language)}</span>
                </div>



                {/* Dispute input */}
                {disputeId === f.id && (
                  <div style={{ marginTop: 12, padding: '12px 14px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: 8, color: 'var(--text-secondary)' }}>
                      {t('disputeNote')}
                    </div>
                    <input className="form-input" style={{ width: '100%', marginBottom: 10 }} value={disputeComment}
                      onChange={e => setDisputeComment(e.target.value)} placeholder={t('disputePlaceholder')} />
                    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setDisputeId(null)}>{t('cancel')}</button>
                      <button className="btn btn-sm" style={{ background: 'var(--warning)', color: '#000' }}
                        disabled={!disputeComment.trim()}
                        onClick={() => disputeMutation.mutate({ id: f.id, comment: disputeComment })}>
                        <RefreshCw size={13} /> {t('reparse')}
                      </button>
                      <button className="btn btn-primary btn-sm"
                        disabled={!disputeComment.trim()}
                        onClick={() => disputeTaskMutation.mutate({ factContent: f.content, comment: disputeComment })}>
                        <ClipboardList size={13} /> {t('submitEvidenceTask')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pagination — always visible */}
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8, padding: '16px 0' }}>
        <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
          <ChevronLeft size={14} /> {t('previousPage')}
        </button>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          {t('pageSummary', { page, totalPages, total: sorted.length })}
        </span>
        <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
          {t('nextPage')} <ChevronRight size={14} />
        </button>
      </div>

      {confirmAction && (
        <ConfirmActionModal
          action={confirmAction.kind}
          itemName={confirmAction.name}
          itemType={t('itemFact')}
          isPending={confirmPending}
          onCancel={() => setConfirmAction(null)}
          onConfirm={confirmFactAction}
        />
      )}

      {translationFact && (
        <div className="confirm-modal-backdrop" onClick={() => setTranslationFact(null)}>
          <div className="confirm-modal-card" style={{ width: 'min(720px, calc(100vw - 32px))' }} onClick={(event) => event.stopPropagation()}>
            <div className="confirm-modal-header">
              <span className="confirm-icon"><Languages size={18} /></span>
              <div>
                <h2>{t('translationResult')}</h2>
                <p>{translationFact.title}</p>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
              <button className={`btn btn-sm ${translateTarget === 'en' ? 'btn-primary' : 'btn-ghost'}`}
                disabled={translatingId === translationFact.id}
                onClick={() => translateFactContent(translationFact.id, translationFact.title, translationFact.original, 'en')}>
                {t('translateToEnglish')}
              </button>
              <button className={`btn btn-sm ${translateTarget === 'zh' ? 'btn-primary' : 'btn-ghost'}`}
                disabled={translatingId === translationFact.id}
                onClick={() => translateFactContent(translationFact.id, translationFact.title, translationFact.original, 'zh')}>
                {t('translateToChinese')}
              </button>
            </div>
            <textarea
              className="form-textarea"
              rows={10}
              value={translationFact.content}
              onChange={(e) => setTranslationFact({ ...translationFact, content: e.target.value })}
              style={{ fontFamily: 'inherit', lineHeight: 1.7 }}
            />
            <div className="confirm-modal-actions">
              <button className="btn btn-ghost" onClick={() => setTranslationFact(null)}>{t('cancel')}</button>
              <button className="btn btn-primary" onClick={applyFactTranslation} disabled={updateMutation.isPending}>
                {updateMutation.isPending ? <span className="spinner" /> : <CheckCircle size={14} />}
                {t('applyTranslation')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
