import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  Plus, FolderOpen, ChevronRight, X, Trash2,
  Edit3
} from 'lucide-react'
import { casesApi } from '../api'
import { ConfirmActionKind, ConfirmActionModal, ObjectLifecycleActions } from '../components/ObjectLifecycleActions'
import { formatLocalDateTime } from '../utils/time'

const CASE_TYPES = ['EB1A', 'EB1B', 'NIW', 'O1A', 'EB2', 'EB3', 'H1B']
const CASE_STATUSES = ['intake', 'fact_extraction', 'drafting', 'review', 'submitted']
const statusColors: Record<string, string> = {
  intake: 'badge-gray', fact_extraction: 'badge-blue', drafting: 'badge-yellow',
  review: 'badge-yellow', submitted: 'badge-green', approved: 'badge-gold',
}
const statusLabels: Record<string, string> = {
  intake: 'intake', fact_extraction: 'factExtraction', drafting: 'drafting',
  review: 'review', submitted: 'submitted', approved: 'approved',
}

type CaseItem = {
  id: string; title: string; case_type: string; status: string;
  created_at: string; updated_at?: string | null; is_deleted: boolean; client_name?: string; client_email?: string; client_phone?: string;
}

export default function CasesPage() {
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()

  // UI state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [viewMode, setViewMode] = useState<'active' | 'trash'>('active')
  const [confirmAction, setConfirmAction] = useState<{ kind: ConfirmActionKind; id: string; name: string } | null>(null)
  const [confirmPending, setConfirmPending] = useState(false)

  // Create form
  const [title, setTitle] = useState('')
  const [caseType, setCaseType] = useState('EB1A')
  const [clientName, setClientName] = useState('')
  const [clientEmail, setClientEmail] = useState('')
  const [clientPhone, setClientPhone] = useState('')

  // Edit form
  const [editId, setEditId] = useState('')
  const [editTitle, setEditTitle] = useState('')
  const [editCaseType, setEditCaseType] = useState('EB1A')
  const [editStatus, setEditStatus] = useState('intake')
  const [editClientName, setEditClientName] = useState('')
  const [editClientEmail, setEditClientEmail] = useState('')
  const [editClientPhone, setEditClientPhone] = useState('')

  // Sort + pagination
  const [sortBy, setSortBy] = useState<'title' | 'case_type' | 'status' | 'updated_at'>('updated_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 10

  // Queries
  const { data: activeData, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => casesApi.list(),
  })
  const { data: trashData, isLoading: trashLoading } = useQuery({
    queryKey: ['cases-trash'],
    queryFn: () => casesApi.trash(),
    enabled: viewMode === 'trash',
  })

  const rawCases: CaseItem[] = viewMode === 'active' ? (activeData?.data ?? []) : (trashData?.data ?? [])
  const sortedCases = [...rawCases].sort((a, b) => {
    const valueForSort = (item: CaseItem) => sortBy === 'updated_at' ? (item.updated_at || item.created_at || '') : ((item as any)[sortBy] ?? '')
    const av = valueForSort(a), bv = valueForSort(b)
    return sortOrder === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
  })
  const totalPages = Math.max(1, Math.ceil(sortedCases.length / PAGE_SIZE))
  const cases = sortedCases.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const toggleSort = (field: typeof sortBy) => {
    if (sortBy === field) setSortOrder(o => o === 'asc' ? 'desc' : 'asc')
    else { setSortBy(field); setSortOrder('desc') }
    setPage(1)
  }
  const sortIndicator = (field: string) => sortBy === field ? (sortOrder === 'asc' ? ' ↑' : ' ↓') : ''

  // Mutations
  const createMutation = useMutation({
    mutationFn: () => casesApi.create({
      title,
      case_type: caseType,
      client_name: clientName,
      client_email: clientEmail,
      client_phone: clientPhone,
    }),
    onSuccess: () => {
      toast.success(t('caseCreated'))
      qc.invalidateQueries({ queryKey: ['cases'] })
      setShowCreateModal(false)
      setTitle('')
      setClientName('')
      setClientEmail('')
      setClientPhone('')
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail || t('createFailed')
      toast.error(typeof detail === 'string' ? detail : t('createInputFailed'))
    },
  })

  const updateMutation = useMutation({
    mutationFn: () => casesApi.update(editId, {
      title: editTitle,
      case_type: editCaseType,
      status: editStatus,
      client_name: editClientName,
      client_email: editClientEmail,
      client_phone: editClientPhone,
    }),
    onSuccess: () => {
      toast.success(t('caseUpdated'))
      qc.invalidateQueries({ queryKey: ['cases'] })
      setShowEditModal(false)
    },
    onError: () => toast.error(t('updateFailed')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => casesApi.softDelete(id),
    onSuccess: () => {
      toast.success(t('movedToTrash'))
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['cases-trash'] })
    },
  })

  const restoreMutation = useMutation({
    mutationFn: (id: string) => casesApi.restore(id),
    onSuccess: () => {
      toast.success(t('caseRestored'))
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['cases-trash'] })
    },
  })

  const permanentDeleteMutation = useMutation({
    mutationFn: (id: string) => casesApi.permanentDelete(id),
    onSuccess: () => {
      toast.success(t('permanentlyDeleted'))
      qc.invalidateQueries({ queryKey: ['cases-trash'] })
    },
  })

  const confirmCaseAction = async () => {
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

  const openEdit = (c: CaseItem) => {
    setEditId(c.id)
    setEditTitle(c.title)
    setEditCaseType(c.case_type)
    setEditStatus(c.status)
    setEditClientName(c.client_name || '')
    setEditClientEmail(c.client_email || '')
    setEditClientPhone(c.client_phone || '')
    setShowEditModal(true)
  }

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>{t('cases')}</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>{t('caseListDescription')}</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {/* View mode toggle */}
          <div style={{
            display: 'flex', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)', overflow: 'hidden',
          }}>
            <button
              className={`btn btn-sm ${viewMode === 'active' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ borderRadius: 0, minWidth: 90 }}
              onClick={() => setViewMode('active')}
            >
              <FolderOpen size={14} /> {t('caseTab')}
            </button>
            <button
              className={`btn btn-sm ${viewMode === 'trash' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ borderRadius: 0, minWidth: 90 }}
              onClick={() => setViewMode('trash')}
            >
              <Trash2 size={14} /> {t('trash')}
            </button>
          </div>
          {viewMode === 'active' && (
            <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
              <Plus size={16} /> {t('newCase')}
            </button>
          )}
        </div>
      </div>

      {/* Case list */}
      <div className="card">
        {(isLoading || trashLoading) ? (
          <div style={{ padding: 60, textAlign: 'center' }}><span className="spinner" /></div>
        ) : cases.length === 0 ? (
          <div style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)' }}>
            {viewMode === 'trash' ? (
              <>
                <Trash2 size={48} style={{ marginBottom: 16, opacity: 0.4 }} />
                <div>{t('emptyTrash')}</div>
              </>
            ) : (
              <>
                <FolderOpen size={48} style={{ marginBottom: 16, opacity: 0.4 }} />
                <div style={{ fontSize: '1rem', marginBottom: 8 }}>{t('noCases')}</div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>{t('createFirstCase')}</button>
              </>
            )}
          </div>
        ) : (
          <>
          <table className="table">
            <thead>
              <tr>
                <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('title')}>{t('caseTitle')}{sortIndicator('title')}</th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('case_type')}>{t('type')}{sortIndicator('case_type')}</th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('status')}>{t('status')}{sortIndicator('status')}</th>
                <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('updated_at')}>{t('updatedAt')}{sortIndicator('updated_at')}</th>
                <th style={{ width: 200 }}>{t('actions')}</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c: CaseItem) => (
                <tr key={c.id}>
                  <td style={{ fontWeight: 500 }}>{c.title}</td>
                  <td><span className="badge badge-blue">{c.case_type}</span></td>
                  <td><span className={`badge ${statusColors[c.status] ?? 'badge-gray'}`}>{statusLabels[c.status] ? t(statusLabels[c.status]) : c.status}</span></td>
                  <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    {formatLocalDateTime(c.updated_at || c.created_at, i18n.language)}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      {viewMode === 'active' ? (
                        <>
                          <Link to={`/cases/${c.id}`}>
                            <button className="btn btn-ghost btn-sm"><ChevronRight size={14} /> {t('enterCase')}</button>
                          </Link>
                          <button className="btn btn-ghost btn-sm" onClick={() => openEdit(c)} title={t('edit')}>
                            <Edit3 size={14} />
                          </button>
                          <ObjectLifecycleActions
                            mode="active"
                            onTrash={() => setConfirmAction({ kind: 'trash', id: c.id, name: c.title })}
                            onRestore={() => restoreMutation.mutate(c.id)}
                            onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: c.id, name: c.title })}
                          />
                        </>
                      ) : (
                        <ObjectLifecycleActions
                          mode="trash"
                          onTrash={() => setConfirmAction({ kind: 'trash', id: c.id, name: c.title })}
                          onRestore={() => restoreMutation.mutate(c.id)}
                          onPermanentDelete={() => setConfirmAction({ kind: 'permanent', id: c.id, name: c.title })}
                        />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalPages > 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 8, padding: '12px 0' }}>
              <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>{t('previousPage')}</button>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{page} / {totalPages}</span>
              <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>{t('nextPage')}</button>
            </div>
          )}
        </>
        )}
      </div>

      {/* ─── Create Modal ──────────────────── */}
      {showCreateModal && (
        <Modal title={t('newCase')} onClose={() => setShowCreateModal(false)}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="form-group">
              <label className="form-label">{t('caseTitle')}</label>
              <input className="form-input" value={title} onChange={e => setTitle(e.target.value)} placeholder="张三 EB-1A 申请" required />
            </div>
            <div className="form-group">
              <label className="form-label">{t('caseType')}</label>
              <select className="form-select" value={caseType} onChange={e => setCaseType(e.target.value)}>
                {CASE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">客户姓名</label>
              <input className="form-input" value={clientName} onChange={e => setClientName(e.target.value)} placeholder="客户姓名（选填）" />
            </div>
            <div className="form-group">
              <label className="form-label">客户邮箱</label>
              <input className="form-input" type="email" value={clientEmail} onChange={e => setClientEmail(e.target.value)} placeholder="client@example.com" />
            </div>
            <div className="form-group">
              <label className="form-label">客户电话</label>
              <input className="form-input" value={clientPhone} onChange={e => setClientPhone(e.target.value)} placeholder="+1 555 000 0000" />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 4 }}>
                客户邮箱或电话至少填写一个
              </span>
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
              <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => setShowCreateModal(false)}>{t('cancel')}</button>
              <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => createMutation.mutate()} disabled={!title || (!clientEmail.trim() && !clientPhone.trim()) || createMutation.isPending}>
                {createMutation.isPending ? <span className="spinner" /> : t('newCase')}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* ─── Edit Modal ────────────────────── */}
      {showEditModal && (
        <Modal title={t('editCase')} onClose={() => setShowEditModal(false)}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="form-group">
              <label className="form-label">{t('caseTitle')}</label>
              <input className="form-input" value={editTitle} onChange={e => setEditTitle(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">{t('caseType')}</label>
              <select className="form-select" value={editCaseType} onChange={e => setEditCaseType(e.target.value)}>
                {CASE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">{t('status')}</label>
              <select className="form-select" value={editStatus} onChange={e => setEditStatus(e.target.value)}>
                {CASE_STATUSES.map(s => <option key={s} value={s}>{statusLabels[s] ? t(statusLabels[s]) : s}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">客户姓名</label>
              <input className="form-input" value={editClientName} onChange={e => setEditClientName(e.target.value)} placeholder="客户姓名（选填）" />
            </div>
            <div className="form-group">
              <label className="form-label">客户邮箱</label>
              <input className="form-input" type="email" value={editClientEmail} onChange={e => setEditClientEmail(e.target.value)} placeholder="client@example.com" />
            </div>
            <div className="form-group">
              <label className="form-label">客户电话</label>
              <input className="form-input" value={editClientPhone} onChange={e => setEditClientPhone(e.target.value)} placeholder="+1 555 000 0000" />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 4 }}>
                客户邮箱或电话至少保留一个
              </span>
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
              <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => setShowEditModal(false)}>{t('cancel')}</button>
              <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => updateMutation.mutate()} disabled={!editTitle || (!editClientEmail.trim() && !editClientPhone.trim()) || updateMutation.isPending}>
                {updateMutation.isPending ? <span className="spinner" /> : t('save')}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {confirmAction && (
        <ConfirmActionModal
          action={confirmAction.kind}
          itemName={confirmAction.name}
          itemType={t('itemCase')}
          isPending={confirmPending}
          onCancel={() => setConfirmAction(null)}
          onConfirm={confirmCaseAction}
        />
      )}
    </div>
  )
}

/** Reusable modal wrapper */
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200,
    }}>
      <div className="card fade-up" style={{ width: 480, maxHeight: 'calc(100vh - 48px)', overflowY: 'auto', padding: 32 }}>
        {title && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700 }}>{title}</h2>
            <button className="btn btn-ghost btn-sm" style={{ padding: 6 }} onClick={onClose}><X size={16} /></button>
          </div>
        )}
        {!title && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <button className="btn btn-ghost btn-sm" style={{ padding: 6 }} onClick={onClose}><X size={16} /></button>
          </div>
        )}
        {children}
      </div>
    </div>
  )
}
