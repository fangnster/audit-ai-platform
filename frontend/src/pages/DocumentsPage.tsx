import { useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useDropzone } from 'react-dropzone'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  Upload, File, CheckCircle, Clock, AlertCircle, RefreshCw, Download,
  ChevronLeft, ChevronRight,
  FolderOpen, Award, BookOpen, FileText, Users, Mic, Shield, Mail, Archive, Wand2, Search
} from 'lucide-react'
import { docsApi, knowledgeApi } from '../api'
import { ConfirmActionKind, ConfirmActionModal, ObjectLifecycleActions } from '../components/ObjectLifecycleActions'
import { formatLocalDateTime } from '../utils/time'
import { readableLlmError } from '../utils/llmError'

const DOC_TYPES = ['evidence', 'award', 'patent', 'publication', 'citation', 'employment', 'media', 'membership', 'reference_letter', 'petition_letter', 'rfi', 'other']
const DOC_TYPE_META: Record<string, { icon: string; labelKey: string }> = {
  evidence: { icon: '📄', labelKey: 'docTypeEvidence' },
  award: { icon: '🏆', labelKey: 'docTypeAward' },
  patent: { icon: '💡', labelKey: 'docTypePatent' },
  publication: { icon: '📝', labelKey: 'docTypePublication' },
  citation: { icon: '📊', labelKey: 'docTypeCitation' },
  employment: { icon: '💼', labelKey: 'docTypeEmployment' },
  media: { icon: '📰', labelKey: 'docTypeMedia' },
  membership: { icon: '🏛️', labelKey: 'docTypeMembership' },
  reference_letter: { icon: '✉️', labelKey: 'docTypeReferenceLetter' },
  petition_letter: { icon: '📋', labelKey: 'docTypePetitionLetter' },
  rfi: { icon: '📮', labelKey: 'docTypeRfi' },
  other: { icon: '📁', labelKey: 'docTypeOther' },
}
const DOC_TYPE_ICONS: Record<string, React.ReactNode> = {
  award: <Award size={16} />, patent: <BookOpen size={16} />, publication: <FileText size={16} />,
  reference_letter: <Mail size={16} />, membership: <Shield size={16} />, media: <Mic size={16} />,
  employment: <Users size={16} />, evidence: <File size={16} />,
}
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

export default function DocumentsPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const docTypeLabel = (type: string, withIcon = false) => {
    const meta = DOC_TYPE_META[type]
    if (!meta) return type
    const label = t(meta.labelKey)
    return withIcon ? `${meta.icon} ${label}` : label
  }
  const [docType, setDocType] = useState('evidence')
  const [catFilter, setCatFilter] = useState('')
  const [uploading, setUploading] = useState(false)
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

  // Fetch knowledge base prompt templates
  const { data: kbData } = useQuery({
    queryKey: ['knowledge', 'prompt_template'],
    queryFn: () => knowledgeApi.list('prompt_template'),
    enabled: Boolean(parseDocId),
  })
  const promptTemplates: any[] = kbData?.data ?? []

  // Also fetch all knowledge items when the parse modal is open (for broader access)
  const { data: kbAllData } = useQuery({
    queryKey: ['knowledge', 'all'],
    queryFn: () => knowledgeApi.list(),
    enabled: Boolean(parseDocId),
  })
  const allKnowledge: any[] = kbAllData?.data ?? []
  const parseKnowledgePool = promptTemplates.length > 0 ? promptTemplates : allKnowledge
  const parseKnowledgeItems = parseKnowledgePool.filter(item => {
    const term = parseKnowledgeSearch.trim().toLowerCase()
    if (!term) return true
    return `${item.title} ${item.content} ${item.item_type}`.toLowerCase().includes(term)
  })

  const { data, isLoading } = useQuery({
    queryKey: ['docs', caseId, 'active'],
    queryFn: () => docsApi.list(caseId!),
  })
  const allDocs: any[] = data?.data ?? []

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

  // Open parse dialog
  const openParseDialog = (docId: string, docName: string) => {
    setParseDocId(docId)
    setParseDocName(docName)
    setParsePrompt('')
    setParseKnowledgeSearch('')
  }

  // Trigger parse with prompt
  const handleParse = async () => {
    if (!parseDocId) return
    setParsing(true)
    try {
      const res = await docsApi.triggerParse(parseDocId, parsePrompt || undefined)
      const promptInfo = parsePrompt ? `（使用提示词）` : ''
      toast.success(`解析完成${promptInfo}，提取 ${res.data.facts_extracted ?? 0} 条事实`)
      qc.invalidateQueries({ queryKey: ['docs', caseId] })
      qc.invalidateQueries({ queryKey: ['facts', caseId] })
      setParseDocId(null)
    } catch (e: any) {
      toast.error(readableLlmError(e, i18n.language, 'parse'))
    }
    finally { setParsing(false) }
  }

  // Load template into prompt
  const loadTemplate = (content: string) => {
    setParsePrompt(prev => prev ? `${prev}\n\n${content}` : content)
    setParseKnowledgeSearch('')
    toast.success(t('templateLoaded'))
  }

  const appendParseGuidance = (content: string) => {
    setParsePrompt(prev => prev ? `${prev}\n- ${content}` : `- ${content}`)
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
            <select className="form-select" style={{ width: 200 }} value={docType} onChange={e => setDocType(e.target.value)}>
              {DOC_TYPES.map(type => <option key={type} value={type}>{docTypeLabel(type, true)}</option>)}
            </select>
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
              {DOC_TYPE_ICONS[type] || <File size={14} />} {docTypeLabel(type)} ({items.length})
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
            <table className="table">
              <thead>
                <tr>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('filename')}>{t('filename')}{sortIndicator('filename')}</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('doc_type')}>{t('type')}{sortIndicator('doc_type')}</th>
                  <th>{t('parseStatus')}</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('created_at')}>{t('time')}{sortIndicator('created_at')}</th>
                  <th style={{ width: 380 }}>{t('actions')}</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d: any) => (
                  <tr key={d.id}>
                    <td style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {DOC_TYPE_ICONS[d.doc_type] || <File size={14} color="var(--text-muted)" />} {d.filename}
                    </td>
                    <td><span className="badge badge-blue">{docTypeLabel(d.doc_type)}</span></td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        {PARSE_STATUS_ICONS[d.parse_status]}
                        <span style={{ fontSize: '0.8rem' }}>{PARSE_LABEL_KEYS[d.parse_status] ? t(PARSE_LABEL_KEYS[d.parse_status]) : d.parse_status}</span>
                      </div>
                    </td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                      <div>{t('updatedAt')}: {formatLocalDateTime(d.updated_at || d.created_at, i18n.language)}</div>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 4 }}>
                        {viewMode === 'active' ? (
                          <>
                            <button className="btn btn-ghost btn-sm" onClick={() => openParseDialog(d.id, d.filename)}
                              title={d.parse_status === 'parsed' ? t('reparse') : t('aiParse')}>
                              <Wand2 size={13} /> {d.parse_status === 'parsed' ? t('reparse') : t('parse')}
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
                ))}
              </tbody>
            </table>

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

      {/* Parse Dialog Modal */}
      {parseDocId && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(0,0,0,0.7)',
        }} onClick={() => !parsing && setParseDocId(null)}>
          <div className="card fade-up" style={{ width: 640, maxHeight: '85vh', overflow: 'auto', padding: 32 }}
            onClick={e => e.stopPropagation()}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: 20 }}>
              <Wand2 size={18} style={{ verticalAlign: 'middle', marginRight: 8 }} />
              {t('aiParse')}
              <span style={{ fontSize: '0.8rem', fontWeight: 400, color: 'var(--text-secondary)', marginLeft: 8 }}>
                {parseDocName}
              </span>
            </h2>

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">{t('parsePromptOptional')}</label>
              <textarea
                className="form-textarea"
                rows={5}
                value={parsePrompt}
                onChange={e => setParsePrompt(e.target.value)}
                placeholder={t('parsePromptPlaceholder')}
                style={{ width: '100%' }}
              />
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {t('parsePromptHint')}
              </span>
            </div>

            <div className="form-group" style={{ marginBottom: 20 }}>
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

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">
                <BookOpen size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
                {t('parseKnowledgeReferenceOptional')}
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
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto', padding: 8, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                {parseKnowledgePool.length === 0 ? (
                  <div style={{ padding: 14, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    {t('emptyParseKnowledge')}
                  </div>
                ) : parseKnowledgeItems.length === 0 ? (
                  <div style={{ padding: 14, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    {t('noKnowledgeMatches')}
                  </div>
                ) : parseKnowledgeItems.map((item: any) => (
                  <button
                    key={item.id}
                    className="btn btn-ghost"
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
                      justifyContent: 'flex-start', textAlign: 'left', height: 'auto',
                    }}
                    onClick={() => loadTemplate(item.content)}
                  >
                    <span>{item.item_type === 'prompt_template' ? '📝' : item.item_type === 'agent_strategy' ? '🎯' : '📄'}</span>
                    <span style={{ minWidth: 0, flex: 1 }}>
                      <span style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title}</span>
                      <span style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.content?.substring(0, 90)}{item.content?.length > 90 ? '…' : ''}
                      </span>
                    </span>
                    <span className="badge badge-gray" style={{ fontSize: '0.7rem', marginLeft: 'auto', flexShrink: 0 }}>
                      {knowledgeTypeLabel(item.item_type)}
                    </span>
                  </button>
                ))}
              </div>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
                {t('parseKnowledgeHint')}
              </span>
            </div>

            <div style={{ display: 'flex', gap: 12 }}>
              <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => setParseDocId(null)} disabled={parsing}>{t('cancel')}</button>
              <button className="btn btn-primary" style={{ flex: 1 }} onClick={handleParse} disabled={parsing}>
                {parsing ? <span className="spinner" /> : <Wand2 size={16} />}
                {parsing ? t('parseParsing') : t('parse')}
              </button>
            </div>
          </div>
        </div>
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
