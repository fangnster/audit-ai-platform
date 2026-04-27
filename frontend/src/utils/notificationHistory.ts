import toast from 'react-hot-toast'

export type NotificationHistoryType = 'success' | 'error'
export type NotificationCategory =
  | 'task_submission'
  | 'agent_document'
  | 'agent_fact'
  | 'agent_draft'
  | 'translation'
  | 'document'
  | 'fact'
  | 'draft'
  | 'case_task'
  | 'knowledge'
  | 'account_system'
  | 'system'

export type NotificationHistoryMeta = {
  type_name?: string
  object_name?: string
  case_title?: string
  case_type?: string
  category?: NotificationCategory
}

export type NotificationHistoryItem = {
  id: string
  type: NotificationHistoryType
  category: NotificationCategory
  message: string
  created_at: string
  path: string
  meta?: NotificationHistoryMeta
}

export type NotificationCategoryPreference = {
  popup: boolean
  history: boolean
}

export type NotificationPreferences = {
  enabled: boolean
  categories: Record<NotificationCategory, NotificationCategoryPreference>
}

export const NOTIFICATION_CATEGORIES: Array<{
  key: NotificationCategory
  labelZh: string
  labelEn: string
  descriptionZh: string
  descriptionEn: string
}> = [
  {
    key: 'task_submission',
    labelZh: '后台任务提交',
    labelEn: 'Background task submission',
    descriptionZh: '解析、重解析、文案生成等任务已进入后台队列的提交提示；不是最终成功或失败结果',
    descriptionEn: 'Queued-task messages for parsing, reparsing, and draft generation; not final success or failure results',
  },
  {
    key: 'agent_document',
    labelZh: '文件解析结果',
    labelEn: 'File parsing results',
    descriptionZh: '文件解析、重新解析的成功和失败结果，以及重复任务、启动失败等解析相关提示',
    descriptionEn: 'Success and failure results for file parsing and reparsing, plus duplicate-task and startup failure notices',
  },
  {
    key: 'agent_fact',
    labelZh: '事实重解析',
    labelEn: 'Fact reparse',
    descriptionZh: '事实有异议后的后台重解析结果',
    descriptionEn: 'Background reparse results after fact disputes',
  },
  {
    key: 'agent_draft',
    labelZh: '文案生成 / AI 重写结果',
    labelEn: 'Draft generation / AI rewrite results',
    descriptionZh: '文案生成、AI 重写、RFI 生成的成功和失败结果，以及重复任务、启动失败等相关提示',
    descriptionEn: 'Success and failure results for draft generation, AI rewrite, and RFI generation, plus related duplicate-task and startup failure notices',
  },
  {
    key: 'translation',
    labelZh: '翻译',
    labelEn: 'Translation',
    descriptionZh: '事实和文案的中英文翻译结果',
    descriptionEn: 'Chinese/English translation results for facts and drafts',
  },
  {
    key: 'document',
    labelZh: '文件操作',
    labelEn: 'Document actions',
    descriptionZh: '上传、下载、导出、删除、恢复文件',
    descriptionEn: 'Upload, download, export, delete, and restore documents',
  },
  {
    key: 'fact',
    labelZh: '事实操作',
    labelEn: 'Fact actions',
    descriptionZh: '确认、编辑、删除、恢复事实及证据任务',
    descriptionEn: 'Confirm, edit, delete, restore facts, and evidence tasks',
  },
  {
    key: 'draft',
    labelZh: '文案操作',
    labelEn: 'Draft actions',
    descriptionZh: '文案编辑、保存、导出、删除、恢复',
    descriptionEn: 'Edit, save, export, delete, and restore draft sections',
  },
  {
    key: 'case_task',
    labelZh: '案件和任务',
    labelEn: 'Cases and tasks',
    descriptionZh: '案件创建、案件状态、律师任务流转',
    descriptionEn: 'Case creation, case status, and lawyer task workflow',
  },
  {
    key: 'knowledge',
    labelZh: '知识库',
    labelEn: 'Knowledge base',
    descriptionZh: '知识库条目的新增、保存、删除、恢复',
    descriptionEn: 'Create, save, delete, and restore knowledge items',
  },
  {
    key: 'account_system',
    labelZh: '账户和系统',
    labelEn: 'Account and system',
    descriptionZh: '登录注册、设置、后台管理、模型测试',
    descriptionEn: 'Login, registration, settings, admin, and model tests',
  },
  {
    key: 'system',
    labelZh: '其他',
    labelEn: 'Other',
    descriptionZh: '无法归入具体业务类别的提示',
    descriptionEn: 'Messages that do not fit a specific workflow category',
  },
]

const STORAGE_KEY = 'notification-history-v1'
const PREFERENCES_KEY = 'notification-preferences-v1'
const MAX_ITEMS = 200
const listeners = new Set<() => void>()
const preferenceListeners = new Set<() => void>()
let installed = false
const CATEGORY_KEYS = new Set(NOTIFICATION_CATEGORIES.map(item => item.key))

function normalizeCategory(value: unknown): NotificationCategory {
  return typeof value === 'string' && CATEGORY_KEYS.has(value as NotificationCategory)
    ? value as NotificationCategory
    : 'system'
}

function defaultCategoryPreferences(): Record<NotificationCategory, NotificationCategoryPreference> {
  return NOTIFICATION_CATEGORIES.reduce((acc, item) => {
    acc[item.key] = { popup: true, history: true }
    return acc
  }, {} as Record<NotificationCategory, NotificationCategoryPreference>)
}

function defaultPreferences(): NotificationPreferences {
  return {
    enabled: true,
    categories: defaultCategoryPreferences(),
  }
}

function safeParse(raw: string | null): NotificationHistoryItem[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(item => (
        item &&
        (item.type === 'success' || item.type === 'error') &&
        typeof item.message === 'string' &&
        typeof item.created_at === 'string'
      ))
      .map(item => ({
        ...item,
        category: normalizeCategory(item.category || item.meta?.category || inferCategoryFromSnapshot(item.path, item.message)),
      }))
  } catch {
    return []
  }
}

function storageAvailable() {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function readItems() {
  if (!storageAvailable()) return []
  try {
    return safeParse(window.localStorage.getItem(STORAGE_KEY))
  } catch {
    return []
  }
}

function writeItems(items: NotificationHistoryItem[]) {
  if (!storageAvailable()) return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)))
  } catch {
    // Notification history is a convenience feature; blocked storage should not break toasts.
  }
}

function emitChange() {
  listeners.forEach(listener => listener())
}

function emitPreferenceChange() {
  preferenceListeners.forEach(listener => listener())
}

function newId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function messageToText(message: Parameters<typeof toast.success>[0]) {
  if (typeof message === 'string') return message
  if (typeof message === 'number' || typeof message === 'boolean') return String(message)
  if (message == null) return ''
  return '[非文本通知]'
}

function cleanMeta(meta?: NotificationHistoryMeta) {
  if (!meta) return undefined
  const typeName = meta.type_name?.trim()
  const objectName = meta.object_name?.trim()
  const caseTitle = meta.case_title?.trim()
  const caseType = meta.case_type?.trim()
  const category = meta.category ? normalizeCategory(meta.category) : undefined
  if (!typeName && !objectName && !caseTitle && !caseType && !category) return undefined
  return {
    ...(typeName ? { type_name: typeName } : {}),
    ...(objectName ? { object_name: objectName } : {}),
    ...(caseTitle ? { case_title: caseTitle } : {}),
    ...(caseType ? { case_type: caseType } : {}),
    ...(category ? { category } : {}),
  }
}

function inferCategoryFromSnapshot(path: string, message: string): NotificationCategory {
  const normalizedPath = (path || '').split('?')[0]
  const text = (message || '').toLowerCase()

  if (/翻译|translate|translation/.test(text)) return 'translation'
  if (/解析|parse/.test(text) && (/\/documents/.test(normalizedPath) || /文件|document/.test(text))) return 'agent_document'
  if (/重解析|异议|reparse|dispute/.test(text) && (/\/facts/.test(normalizedPath) || /事实|fact/.test(text))) return 'agent_fact'
  if (/文案生成|ai\s*重写|重写|draft generation|rewrite|rfi/.test(text)) return 'agent_draft'

  if (/\/documents/.test(normalizedPath)) return 'document'
  if (/\/facts/.test(normalizedPath)) return 'fact'
  if (/\/drafts/.test(normalizedPath)) return 'draft'
  if (/\/tasks|\/cases/.test(normalizedPath)) return 'case_task'
  if (/\/knowledge/.test(normalizedPath)) return 'knowledge'
  if (/\/settings|\/admin|\/login|\/register/.test(normalizedPath)) return 'account_system'
  return 'system'
}

function inferNotificationCategory(meta: NotificationHistoryMeta | undefined, message: Parameters<typeof toast.success>[0]) {
  if (meta?.category) return normalizeCategory(meta.category)
  const path = typeof window !== 'undefined' ? `${window.location.pathname}${window.location.search}` : ''
  return inferCategoryFromSnapshot(path, messageToText(message))
}

function normalizePreferences(value: unknown): NotificationPreferences {
  if (!value || typeof value !== 'object') return defaultPreferences()
  const raw = value as Partial<NotificationPreferences>
  const categories = defaultCategoryPreferences()
  const rawCategories = raw.categories && typeof raw.categories === 'object' ? raw.categories : {}
  NOTIFICATION_CATEGORIES.forEach(item => {
    const rawPreference = (rawCategories as Record<string, Partial<NotificationCategoryPreference>>)[item.key] || {}
    categories[item.key] = {
      popup: rawPreference.popup !== false,
      history: rawPreference.history !== false,
    }
  })
  return {
    enabled: raw.enabled !== false,
    categories,
  }
}

function readPreferences(): NotificationPreferences {
  if (!storageAvailable()) return defaultPreferences()
  try {
    return normalizePreferences(JSON.parse(window.localStorage.getItem(PREFERENCES_KEY) || 'null'))
  } catch {
    return defaultPreferences()
  }
}

function writePreferences(preferences: NotificationPreferences) {
  if (!storageAvailable()) return
  try {
    window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify(normalizePreferences(preferences)))
  } catch {
    // Preference persistence is best-effort.
  }
}

function canPopup(category: NotificationCategory) {
  const preferences = readPreferences()
  return preferences.enabled && preferences.categories[category]?.popup !== false
}

function canRecord(category: NotificationCategory) {
  const preferences = readPreferences()
  return preferences.enabled && preferences.categories[category]?.history !== false
}

function recordNotification(type: NotificationHistoryType, message: Parameters<typeof toast.success>[0], category: NotificationCategory, meta?: NotificationHistoryMeta) {
  const text = messageToText(message).trim()
  if (!text) return
  const item: NotificationHistoryItem = {
    id: newId(),
    type,
    category,
    message: text,
    created_at: new Date().toISOString(),
    path: typeof window !== 'undefined' ? `${window.location.pathname}${window.location.search}` : '',
    meta: cleanMeta(meta),
  }
  writeItems([item, ...readItems()])
  emitChange()
}

type ToastHistoryOptions = {
  historyMeta?: NotificationHistoryMeta
  history?: boolean
}

function splitHistoryOptions<T extends object | undefined>(options: T) {
  const historyOptions = options as (T & ToastHistoryOptions) | undefined
  if (!historyOptions) return { toastOptions: options, historyMeta: undefined, shouldRecord: true }
  const { historyMeta, history, ...toastOptions } = historyOptions as ToastHistoryOptions & Record<string, unknown>
  return {
    toastOptions: toastOptions as T,
    historyMeta,
    shouldRecord: history !== false,
  }
}

export function installToastHistoryRecorder() {
  if (installed) return
  installed = true

  const originalSuccess = toast.success.bind(toast)
  const originalError = toast.error.bind(toast)

  toast.success = ((message, options) => {
    const { toastOptions, historyMeta, shouldRecord } = splitHistoryOptions(options)
    const category = inferNotificationCategory(historyMeta, message)
    if (shouldRecord && canRecord(category)) recordNotification('success', message, category, historyMeta)
    if (canPopup(category)) return originalSuccess(message, toastOptions)
    return '' as ReturnType<typeof originalSuccess>
  }) as typeof toast.success

  toast.error = ((message, options) => {
    const { toastOptions, historyMeta, shouldRecord } = splitHistoryOptions(options)
    const category = inferNotificationCategory(historyMeta, message)
    if (shouldRecord && canRecord(category)) recordNotification('error', message, category, historyMeta)
    if (canPopup(category)) return originalError(message, toastOptions)
    return '' as ReturnType<typeof originalError>
  }) as typeof toast.error
}

export function notificationHistoryMeta(meta: NotificationHistoryMeta) {
  return { historyMeta: meta } as Parameters<typeof toast.success>[1]
}

export function getNotificationHistory() {
  return readItems()
}

export function getNotificationPreferences() {
  return readPreferences()
}

export function setNotificationPreferences(preferences: NotificationPreferences) {
  writePreferences(preferences)
  emitPreferenceChange()
}

export function resetNotificationPreferences() {
  writePreferences(defaultPreferences())
  emitPreferenceChange()
}

export function notificationCategoryLabel(category: NotificationCategory, language: string) {
  const item = NOTIFICATION_CATEGORIES.find(option => option.key === category)
  if (!item) return language.startsWith('zh') ? '其他' : 'Other'
  return language.startsWith('zh') ? item.labelZh : item.labelEn
}

export function notificationCategoryDescription(category: NotificationCategory, language: string) {
  const item = NOTIFICATION_CATEGORIES.find(option => option.key === category)
  if (!item) return ''
  return language.startsWith('zh') ? item.descriptionZh : item.descriptionEn
}

export function clearNotificationHistory(type?: NotificationHistoryType, category?: NotificationCategory) {
  if (!type && !category) {
    writeItems([])
  } else {
    writeItems(readItems().filter(item => {
      const typeMatches = !type || item.type === type
      const categoryMatches = !category || item.category === category
      return !(typeMatches && categoryMatches)
    }))
  }
  emitChange()
}

export function subscribeNotificationHistory(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function subscribeNotificationPreferences(listener: () => void) {
  preferenceListeners.add(listener)
  return () => {
    preferenceListeners.delete(listener)
  }
}
