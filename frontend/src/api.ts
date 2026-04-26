import axios from 'axios'
import { useAuthStore } from './store/auth'

const defaultApiBaseURL =
  typeof window !== 'undefined' && window.location.hostname.endsWith('.vercel.app')
    ? 'https://api-production-7601.up.railway.app/api/v1'
    : '/api/v1'

const apiBaseURL = import.meta.env.VITE_API_BASE_URL?.trim() || defaultApiBaseURL

export const api = axios.create({
  baseURL: apiBaseURL,
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT automatically
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Auto-logout on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      useAuthStore.getState().logout()
      localStorage.removeItem('auth-store')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

// ── Auth ──────────────────────────────────
export const authApi = {
  login: (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password })
    return api.post('/auth/login', form, { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
  },
  register: (email: string, name: string, password: string, orgName: string) =>
    api.post('/auth/register', { email, name, password, org_name: orgName.trim() }),
  me: (token?: string) =>
    api.get('/auth/me', token ? { headers: { Authorization: `Bearer ${token}` } } : {}),
  updateMe: (data: { name?: string; phone?: string }) =>
    api.patch('/auth/me', data),
}

// ── Pagination params helper ─────────────
type PaginationParams = { page?: number; page_size?: number; sort_by?: string; sort_order?: 'asc'|'desc' }

// ── Cases ─────────────────────────────────
export const casesApi = {
  list: (params?: PaginationParams) => api.get('/cases', { params }),
  get: (id: string) => api.get(`/cases/${id}`),
  create: (data: { title: string; case_type: string; client_name?: string; client_email?: string; client_phone?: string }) =>
    api.post('/cases', data),
  update: (id: string, data: { title?: string; case_type?: string; status?: string; client_name?: string; client_email?: string; client_phone?: string }) =>
    api.patch(`/cases/${id}`, data),
  softDelete: (id: string) => api.delete(`/cases/${id}`),
  trash: () => api.get('/cases/trash'),
  restore: (id: string) => api.post(`/cases/${id}/restore`),
  permanentDelete: (id: string) => api.delete(`/cases/${id}/permanent`),
  updateStatus: (id: string, status: string) =>
    api.patch(`/cases/${id}/status`, { status }),
}

// ── Documents ─────────────────────────────
export const docsApi = {
  list: (caseId: string, docType?: string) =>
    api.get(`/documents/cases/${caseId}/documents`, { params: docType ? { doc_type: docType } : {} }),
  trash: (caseId: string) =>
    api.get(`/documents/cases/${caseId}/documents`, { params: { show_deleted: true } }),
  upload: (caseId: string, file: File, docType: string, categoryId?: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('doc_type', docType)
    if (categoryId) fd.append('category_id', categoryId)
    return api.post(`/documents/cases/${caseId}/documents`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  categories: () => api.get('/documents/categories'),
  triggerParse: (docId: string, prompt?: string) => api.post(`/documents/${docId}/parse`, prompt ? { prompt } : {}),
  update: (docId: string, data: { doc_type?: string }) => api.patch(`/documents/${docId}`, data),
  softDelete: (docId: string) => api.delete(`/documents/${docId}`),
  restore: (docId: string) => api.post(`/documents/${docId}/restore`),
  permanentDelete: (docId: string) => api.delete(`/documents/${docId}/permanent`),
  download: (docId: string) => api.get(`/documents/${docId}/download`, { responseType: 'blob' }),
  exportText: (docId: string, fmt: string = 'txt') =>
    api.get(`/documents/${docId}/export-text`, { params: { export_format: fmt }, responseType: 'blob' }),
}

// ── Facts ─────────────────────────────────
export const factsApi = {
  list: (caseId: string, params?: PaginationParams) => api.get(`/facts/cases/${caseId}/facts`, { params }),
  trash: (caseId: string, params?: PaginationParams) => api.get(`/facts/cases/${caseId}/facts/trash`, { params }),
  approve: (factId: string) => api.post(`/facts/${factId}/approve`),
  dispute: (factId: string, comment: string) =>
    api.post(`/facts/${factId}/dispute`, { comment }),
  confirm: (factId: string) => api.post(`/facts/${factId}/approve`),  // kept for backward compat, maps to approve
  update: (factId: string, data: { content?: string; category?: string }) =>
    api.patch(`/facts/${factId}`, data),
  softDelete: (factId: string) => api.delete(`/facts/${factId}`),
  restore: (factId: string) => api.post(`/facts/${factId}/restore`),
  permanentDelete: (factId: string) => api.delete(`/facts/${factId}/permanent`),
  uploadEvidence: (caseId: string, file: File, sourceType: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('source_type', sourceType)
    return api.post(`/facts/cases/${caseId}/upload-evidence`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}

// ── Drafts ────────────────────────────────
export const draftsApi = {
  generate: (caseId: string, title: string, prompt: string, strategy: string, knowledgeIds?: string[], factIds?: string[]) =>
    api.post(`/drafts/cases/${caseId}/generate`, { title, prompt, strategy, knowledge_ids: knowledgeIds || [], fact_ids: factIds || [] }),
  list: (caseId: string, version?: string, params?: PaginationParams) =>
    api.get(`/drafts/cases/${caseId}`, { params: { version, ...params } }),
  getSection: (sectionId: string) => api.get(`/drafts/sections/${sectionId}`),
  rewrite: (sectionId: string, instruction: string, strategy: string, knowledgeIds?: string[], factIds?: string[]) =>
    api.post(`/drafts/sections/${sectionId}/rewrite`, { instruction, strategy, knowledge_ids: knowledgeIds || [], fact_ids: factIds || [] }),
  agentTasks: (caseId: string, params?: { sort_order?: 'asc'|'desc' }) =>
    api.get(`/drafts/cases/${caseId}/agent-tasks`, { params }),
  update: (sectionId: string, data: { content_preview?: string; section_title?: string }) =>
    api.patch(`/drafts/sections/${sectionId}`, data),
  softDelete: (sectionId: string) => api.delete(`/drafts/sections/${sectionId}`),
  restore: (sectionId: string) => api.post(`/drafts/sections/${sectionId}/restore`),
  permanentDelete: (sectionId: string) => api.post(`/drafts/sections/${sectionId}/permanent-delete`),
  trash: (caseId: string, version?: string, params?: PaginationParams) =>
    api.get(`/drafts/cases/${caseId}/trash`, { params: { version, ...params } }),
  exportDrafts: (caseId: string, version?: string, format: string = 'docx') =>
    api.get(`/drafts/cases/${caseId}/export`, {
      params: { version, format },
      responseType: 'blob',
    }),
  exportSection: (sectionId: string, format: string = 'docx') =>
    api.get(`/drafts/sections/${sectionId}/export`, {
      params: { format },
      responseType: 'blob',
    }),
  revisions: (sectionId: string) => api.get(`/drafts/sections/${sectionId}/revisions`),
  restoreRevision: (sectionId: string, revisionId: string) =>
    api.post(`/drafts/sections/${sectionId}/revisions/${revisionId}/restore`),
}

// ── Tasks ─────────────────────────────────
export const tasksApi = {
  list: (caseId: string, params?: PaginationParams) => api.get(`/tasks/cases/${caseId}`, { params }),
  create: (caseId: string, data: { title: string; description?: string; task_type?: string }) =>
    api.post(`/tasks/cases/${caseId}`, data),
  approve: (taskId: string) => api.post(`/tasks/${taskId}/approve`),
  complete: (taskId: string) => api.post(`/tasks/${taskId}/complete`),
  updateStatus: (taskId: string, status: string) => api.patch(`/tasks/${taskId}`, { status }),
  update: (taskId: string, data: { title?: string; description?: string; status?: string }) =>
    api.patch(`/tasks/${taskId}`, data),
  softDelete: (taskId: string) => api.delete(`/tasks/${taskId}`),
  restore: (taskId: string) => api.post(`/tasks/${taskId}/restore`),
}

// ── Sessions (auto-save) ──────────────────
export const sessionsApi = {
  get: (caseId: string) => api.get(`/sessions/${caseId}`),
  save: (caseId: string, data: Record<string, unknown>) =>
    api.post(`/sessions/${caseId}`, data),
}

// ── Translation ───────────────────────────
export const translateApi = {
  translate: (content: string, sourceLang: string, targetLang: string) =>
    api.post('/translate', { content, source_lang: sourceLang, target_lang: targetLang }),
}

export const orgApi = {
  me: () => api.get('/orgs/me'),
  settings: () => api.get('/orgs/me/settings'),
  updateSettings: (data: { llm_provider?: string; llm_model?: string; llm_base_url?: string; api_key?: string }) =>
    api.patch('/orgs/me/settings', data),
  testGeneration: () => api.post('/orgs/me/settings/test-generation', {}),
}

// ── Knowledge Base ────────────────────────
export const knowledgeApi = {
  list: (itemType?: string) => api.get('/knowledge', { params: itemType ? { item_type: itemType } : {} }),
  create: (data: { title: string; content: string; item_type: string; tags?: string[] }) =>
    api.post('/knowledge', data),
  update: (id: string, data: { title?: string; content?: string; tags?: string[] }) =>
    api.patch(`/knowledge/${id}`, data),
  softDelete: (id: string) => api.delete(`/knowledge/${id}`),
  trash: () => api.get('/knowledge/trash'),
  restore: (id: string) => api.post(`/knowledge/${id}/restore`),
  permanentDelete: (id: string) => api.delete(`/knowledge/${id}/permanent`),
}
