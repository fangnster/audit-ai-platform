import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  Plus, BookOpen, Edit3, Trash,
  ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Search
} from 'lucide-react'
import { knowledgeApi } from '../api'
import { ConfirmActionKind, ConfirmActionModal, ObjectLifecycleActions } from '../components/ObjectLifecycleActions'
import { formatLocalDateTime } from '../utils/time'
import { notificationHistoryMeta } from '../utils/notificationHistory'

type KnowledgeItem = {
  id: string; title: string; content: string; item_type: string;
  tags: string[]; is_deleted: boolean; created_at: string; updated_at: string;
}

const TYPE_META: Record<string, { icon: string; labelKey: string; color: string }> = {
  prompt_template:    { icon: '🧠', labelKey: 'promptTemplate', color: 'var(--accent-primary)' },
  document_template:  { icon: '📋', labelKey: 'documentTemplate',   color: 'var(--success)' },
  sample_document:    { icon: '📄', labelKey: 'sampleDocument',       color: 'var(--gold)' },
  agent_strategy:     { icon: '🎯', labelKey: 'agentStrategy',         color: 'var(--warning)' },
}
const TYPES = Object.keys(TYPE_META)
const PAGE_SIZE = 8

export default function KnowledgePage() {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const [viewMode, setViewMode] = useState<'active' | 'trash'>('active')
  const [filterType, setFilterType] = useState<string>('')
  const [searchTerm, setSearchTerm] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<{ kind: ConfirmActionKind; id: string; name: string } | null>(null)
  const [confirmPending, setConfirmPending] = useState(false)

  // Form
  const [formTitle, setFormTitle] = useState('')
  const [formContent, setFormContent] = useState('')
  const [formType, setFormType] = useState('prompt_template')
  const [formTags, setFormTags] = useState('')

  // Pagination
  const [page, setPage] = useState(1)

  const { data: activeData } = useQuery({ queryKey: ['knowledge', 'active', filterType], queryFn: () => knowledgeApi.list(filterType || undefined) })
  const { data: activeAllData } = useQuery({ queryKey: ['knowledge', 'active', 'all-counts'], queryFn: () => knowledgeApi.list() })
  const { data: trashData } = useQuery({ queryKey: ['knowledge', 'trash'], queryFn: () => knowledgeApi.trash(), enabled: viewMode === 'trash' })

  const rawItems: KnowledgeItem[] = viewMode === 'active' ? (activeData?.data ?? []) : (trashData?.data ?? [])
  const activeItems: KnowledgeItem[] = activeAllData?.data ?? activeData?.data ?? []
  const normalizedSearch = viewMode === 'active' ? searchTerm.trim().toLowerCase() : ''
  const filteredItems = normalizedSearch
    ? rawItems.filter(item => {
      const text = `${item.title} ${(item.tags || []).join(' ')}`.toLowerCase()
      return text.includes(normalizedSearch)
    })
    : rawItems
  const totalPages = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE))
  const items = filteredItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const typeCounts = TYPES.reduce<Record<string, number>>((acc, type) => {
    acc[type] = activeItems.filter(item => item.item_type === type).length
    return acc
  }, {})
  const knowledgeTypeName = (type: string) => TYPE_META[type] ? t(TYPE_META[type].labelKey) : t('itemKnowledge')
  const findKnowledgeById = (id: string) => [...rawItems, ...activeItems].find(item => item.id === id)
  const knowledgeHistoryMeta = (title?: string, type = formType) => notificationHistoryMeta({
    category: 'knowledge',
    type_name: knowledgeTypeName(type),
    object_name: title || t('itemKnowledge'),
  })
  const knowledgeActionMeta = (id: string, fallbackName?: string) => {
    const item = findKnowledgeById(id)
    return knowledgeHistoryMeta(fallbackName || item?.title || confirmAction?.name, item?.item_type || formType)
  }

  useEffect(() => { setPage(1) }, [viewMode, filterType, searchTerm])

  const createMutation = useMutation({
    mutationFn: () => knowledgeApi.create({
      title: formTitle, content: formContent, item_type: formType,
      tags: formTags.split(',').map(t => t.trim()).filter(Boolean),
    }),
    onSuccess: () => {
      toast.success(t('created'), knowledgeHistoryMeta(formTitle, formType))
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      resetForm()
    },
    onError: (error: any) => toast.error(error?.response?.data?.detail || t('createFailed'), knowledgeHistoryMeta(formTitle, formType)),
  })

  const updateMutation = useMutation({
    mutationFn: () => knowledgeApi.update(editId!, {
      title: formTitle, content: formContent,
      tags: formTags.split(',').map(t => t.trim()).filter(Boolean),
    }),
    onSuccess: () => {
      toast.success(t('saved'), knowledgeHistoryMeta(formTitle, formType))
      qc.invalidateQueries({ queryKey: ['knowledge'] })
      resetForm()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => knowledgeApi.softDelete(id),
    onSuccess: (_data, id) => {
      toast.success(t('movedToTrash'), knowledgeActionMeta(id))
      qc.invalidateQueries({ queryKey: ['knowledge'] })
    },
  })

  const restoreMutation = useMutation({
    mutationFn: (id: string) => knowledgeApi.restore(id),
    onSuccess: (_data, id) => {
      toast.success(t('restored'), knowledgeActionMeta(id))
      qc.invalidateQueries({ queryKey: ['knowledge'] })
    },
  })

  const permanentDeleteMutation = useMutation({
    mutationFn: (id: string) => knowledgeApi.permanentDelete(id),
    onSuccess: (_data, id) => {
      toast.success(t('permanentlyDeleted'), knowledgeActionMeta(id))
      qc.invalidateQueries({ queryKey: ['knowledge'] })
    },
  })

  const confirmKnowledgeAction = async () => {
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

  const resetForm = () => {
    setShowCreate(false); setEditId(null)
    setFormTitle(''); setFormContent(''); setFormType('prompt_template'); setFormTags('')
  }

  const startEdit = (item: KnowledgeItem) => {
    setEditId(item.id); setShowCreate(true)
    setFormTitle(item.title); setFormContent(item.content)
    setFormType(item.item_type); setFormTags(item.tags.join(', '))
  }

  const formContentPlaceholder = () => {
    if (formType === 'prompt_template') return t('promptTemplatePlaceholder')
    if (formType === 'agent_strategy') return t('agentStrategyPlaceholder')
    return t('contentTemplatePlaceholder')
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>📚 {t('lawyerKnowledge')}</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
            {t('knowledgeDescription')}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={`btn ${viewMode === 'active' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => { setViewMode('active'); setPage(1) }}>
            <BookOpen size={16} /> {t('knowledge')}
          </button>
          <button className={`btn ${viewMode === 'trash' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => { setViewMode('trash'); setPage(1) }}>
            <Trash size={16} /> {t('trash')}
          </button>
          {viewMode === 'active' && (
            <button className="btn btn-gold" onClick={() => { resetForm(); setShowCreate(true) }}>
              <Plus size={16} /> {t('new')}
            </button>
          )}
        </div>
      </div>

      {/* Type filter */}
      {viewMode === 'active' && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 12 }}>
            {TYPES.map(type => {
              const meta = TYPE_META[type]
              return (
                <button
                  key={type}
                  className={`btn ${filterType === type ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ justifyContent: 'space-between', padding: '12px 14px', minHeight: 54 }}
                  onClick={() => setFilterType(filterType === type ? '' : type)}
                >
                  <span>{meta.icon} {t(meta.labelKey)}</span>
                  <span className="badge badge-gray">{typeCounts[type] || 0}</span>
                </button>
              )
            })}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className={`btn btn-sm ${!filterType ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setFilterType('')}>{t('all')}</button>
            <div style={{ position: 'relative', flex: 1 }}>
              <Search size={15} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                className="form-input"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                placeholder={t('searchKnowledgePlaceholder')}
                style={{ paddingLeft: 36, height: 36 }}
              />
            </div>
            {searchTerm && (
              <button className="btn btn-ghost btn-sm" onClick={() => setSearchTerm('')}>{t('clear')}</button>
            )}
          </div>
        </div>
      )}

      {/* Items list */}
      {items.length === 0 ? (
        <div className="card" style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: 16 }}>📚</div>
          {viewMode === 'trash' ? t('emptyTrash') : (searchTerm ? t('noKnowledgeMatches') : t('emptyKnowledge'))}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map(item => {
            const meta = TYPE_META[item.item_type] || TYPE_META.prompt_template
            return (
              <div key={item.id} className="card" style={{ overflow: 'hidden' }}>
                <div style={{ padding: '14px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                  onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
                    <span style={{ fontSize: '1.2rem' }}>{meta.icon}</span>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 600 }}>{item.title}</span>
                        <span className="badge" style={{ background: `${meta.color}20`, color: meta.color, fontSize: '0.72rem' }}>
                          {t(meta.labelKey)}
                        </span>
                        {item.tags?.map((tag: string) => (
                          <span key={tag} className="badge badge-gray" style={{ fontSize: '0.7rem' }}>{tag}</span>
                        ))}
                      </div>
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.content ? item.content.replace(/\s+/g, ' ').slice(0, 120) : t('emptyContent')}
                      </div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {t('updatedAt')}: {formatLocalDateTime(item.updated_at || item.created_at, i18n.language)}
                    </span>
                    {viewMode === 'active' ? (
                      <>
                        <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); startEdit(item) }}><Edit3 size={13} /></button>
                        <ObjectLifecycleActions
                          mode="active"
                          stopPropagation
                          onTrash={() => setConfirmAction({ kind: 'trash', id: item.id, name: item.title })}
                          onRestore={() => restoreMutation.mutate(item.id)}
                          onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: item.id, name: item.title })}
                        />
                      </>
                    ) : (
                      <ObjectLifecycleActions
                        mode="trash"
                        stopPropagation
                        onTrash={() => setConfirmAction({ kind: 'trash', id: item.id, name: item.title })}
                        onRestore={() => restoreMutation.mutate(item.id)}
                        onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: item.id, name: item.title })}
                      />
                    )}
                    {expandedId === item.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </div>
                </div>
                {expandedId === item.id && (
                  <div style={{ borderTop: '1px solid var(--border)', padding: '16px 20px', whiteSpace: 'pre-wrap', fontSize: '0.875rem', lineHeight: 1.7, color: 'var(--text-secondary)' }}>
                    {item.content || t('emptyContent')}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 20 }}>
          <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}><ChevronLeft size={14} /></button>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', lineHeight: '32px' }}>{page} / {totalPages}</span>
          <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}><ChevronRight size={14} /></button>
        </div>
      )}

      {/* Create/Edit Modal */}
      {showCreate && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}>
          <div className="card fade-up" style={{ width: 600, maxHeight: '80vh', overflow: 'auto', padding: 32 }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: 20 }}>
              {editId ? t('editKnowledgeItem') : t('newKnowledgeItem')}
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="form-group">
                <label className="form-label">{t('title')}</label>
                <input className="form-input" value={formTitle} onChange={e => setFormTitle(e.target.value)} placeholder={t('titlePlaceholder')} />
              </div>
              {!editId && (
                <div className="form-group">
                  <label className="form-label">{t('type')}</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {TYPES.map(type => (
                      <button key={type} className={`btn btn-sm ${formType === type ? 'btn-primary' : 'btn-ghost'}`}
                        onClick={() => setFormType(type)}>
                        {TYPE_META[type].icon} {t(TYPE_META[type].labelKey)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="form-group">
                <label className="form-label">{t('content')}</label>
                <textarea className="form-textarea" rows={10} value={formContent} onChange={e => setFormContent(e.target.value)}
                  placeholder={formContentPlaceholder()} />
              </div>
              <div className="form-group">
                <label className="form-label">{t('tags')}</label>
                <input className="form-input" value={formTags} onChange={e => setFormTags(e.target.value)} placeholder={t('tagsPlaceholder')} />
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <button className="btn btn-ghost" style={{ flex: 1 }} onClick={resetForm}>{t('cancel')}</button>
                <button className="btn btn-primary" style={{ flex: 1 }}
                  onClick={() => editId ? updateMutation.mutate() : createMutation.mutate()}
                  disabled={!formTitle || !formContent}>
                  {editId ? t('saveChanges') : t('create')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {confirmAction && (
        <ConfirmActionModal
          action={confirmAction.kind}
          itemName={confirmAction.name}
          itemType={t('itemKnowledge')}
          isPending={confirmPending}
          onCancel={() => setConfirmAction(null)}
          onConfirm={confirmKnowledgeAction}
        />
      )}
    </div>
  )
}
