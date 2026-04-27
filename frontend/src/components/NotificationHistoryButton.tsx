import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Bell, CheckCircle2, Search, Trash2, X } from 'lucide-react'
import {
  clearNotificationHistory,
  getNotificationHistory,
  notificationCategoryLabel,
  subscribeNotificationHistory,
  type NotificationHistoryItem,
  type NotificationHistoryType,
} from '../utils/notificationHistory'
import { formatLocalDateTime } from '../utils/time'

type FilterType = 'all' | NotificationHistoryType

const filterOptions: Array<{ key: FilterType; labelKey: string }> = [
  { key: 'all', labelKey: 'notificationFilterAll' },
  { key: 'success', labelKey: 'notificationFilterSuccess' },
  { key: 'error', labelKey: 'notificationFilterError' },
]

function sourceLabel(path: string, language: string) {
  const zh = language.startsWith('zh')
  const normalized = path.split('?')[0]
  if (!normalized || normalized === '/') return zh ? '仪表盘' : 'Dashboard'
  if (normalized === '/cases') return zh ? '案件列表' : 'Case List'
  if (normalized === '/knowledge') return zh ? '知识库' : 'Knowledge'
  if (normalized === '/tasks') return zh ? '任务中心' : 'Task Center'
  if (normalized === '/admin') return zh ? '系统后台' : 'Admin'
  if (normalized === '/settings') return zh ? '设置' : 'Settings'
  if (normalized === '/login') return zh ? '登录页' : 'Login'
  if (normalized === '/register') return zh ? '注册页' : 'Register'
  if (/^\/cases\/[^/]+\/documents/.test(normalized)) return zh ? '案件文档' : 'Case Documents'
  if (/^\/cases\/[^/]+\/facts/.test(normalized)) return zh ? '案件事实' : 'Case Facts'
  if (/^\/cases\/[^/]+\/drafts/.test(normalized)) return zh ? '文案生成' : 'Draft Generation'
  if (/^\/cases\/[^/]+\/tasks/.test(normalized)) return zh ? '案件任务' : 'Case Tasks'
  if (/^\/cases\/[^/]+\/agent-runs/.test(normalized)) return zh ? 'Agent 运行记录' : 'Agent Run Log'
  if (/^\/cases\/[^/]+/.test(normalized)) return zh ? '案件详情' : 'Case Detail'
  return zh ? '当前页面' : 'Current Page'
}

function shortText(value: string, maxLength = 90) {
  const text = value.trim()
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function typeName(item: NotificationHistoryItem, language: string) {
  return item.meta?.type_name?.trim() || sourceLabel(item.path, language)
}

function objectName(item: NotificationHistoryItem, language: string) {
  if (item.meta?.object_name?.trim()) return shortText(item.meta.object_name)
  const text = item.message.trim()
  const quoted = text.match(/[「“"]([^」”"]{2,120})[」”"]/)
  if (quoted?.[1]) return shortText(quoted[1])

  const uploadName = text.match(/^(.+?)\s+上传成功/)
  if (uploadName?.[1]) return shortText(uploadName[1])

  const colonName = text.match(/[：:]([^：:]+)$/)
  if (colonName?.[1]) return shortText(colonName[1])

  const fileName = text.match(/([^，,；;\s]+?\.(?:pdf|docx?|txt|rtf|png|jpe?g|xlsx?|csv|pptx?))/i)
  if (fileName?.[1]) return shortText(fileName[1])

  return sourceLabel(item.path, language)
}

function caseContext(item: NotificationHistoryItem) {
  const caseTitle = item.meta?.case_title?.trim()
  const caseType = item.meta?.case_type?.trim()
  return [caseTitle ? shortText(caseTitle, 80) : '', caseType || ''].filter(Boolean).join(' · ')
}

function caseTitle(item: NotificationHistoryItem) {
  return item.meta?.case_title?.trim() || ''
}

function caseType(item: NotificationHistoryItem) {
  return item.meta?.case_type?.trim() || ''
}

export default function NotificationHistoryButton() {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState<FilterType>('all')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<NotificationHistoryItem[]>(() => getNotificationHistory())

  useEffect(() => {
    return subscribeNotificationHistory(() => setItems(getNotificationHistory()))
  }, [])

  const counts = useMemo(() => ({
    all: items.length,
    success: items.filter(item => item.type === 'success').length,
    error: items.filter(item => item.type === 'error').length,
  }), [items])

  const visibleItems = useMemo(() => {
    const term = query.trim().toLowerCase()
    return items.filter(item => {
      if (filter !== 'all' && item.type !== filter) return false
      if (!term) return true
      return `${item.message} ${notificationCategoryLabel(item.category, i18n.language)} ${caseContext(item)} ${typeName(item, i18n.language)} ${objectName(item, i18n.language)}`.toLowerCase().includes(term)
    })
  }, [filter, i18n.language, items, query])

  const clearCurrent = () => {
    clearNotificationHistory(filter === 'all' ? undefined : filter)
  }

  return (
    <div className="notification-history">
      <button
        className="btn btn-ghost btn-sm notification-history-trigger"
        onClick={() => setOpen(value => !value)}
        title={t('notificationHistory')}
      >
        <Bell size={14} />
        {t('alerts')}
        {items.length > 0 && <span className="notification-history-count">{items.length > 99 ? '99+' : items.length}</span>}
      </button>

      {open && (
        <div className="notification-history-panel">
          <div className="notification-history-header">
            <div>
              <div className="notification-history-title">{t('notificationHistory')}</div>
              <div className="notification-history-subtitle">{t('notificationHistorySubtitle')}</div>
            </div>
            <button className="btn btn-ghost btn-sm notification-history-close" onClick={() => setOpen(false)} title={t('close')}>
              <X size={15} />
            </button>
          </div>

          <div className="notification-history-controls">
            <div className="notification-history-tabs">
              {filterOptions.map(option => (
                <button
                  key={option.key}
                  className={`btn btn-sm ${filter === option.key ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setFilter(option.key)}
                >
                  {t(option.labelKey)} ({counts[option.key]})
                </button>
              ))}
            </div>

            <label className="notification-history-search">
              <Search size={14} />
              <input
                value={query}
                onChange={event => setQuery(event.target.value)}
                placeholder={t('notificationSearchPlaceholder')}
              />
            </label>
          </div>

          <div className="notification-history-list">
            {visibleItems.length === 0 ? (
              <div className="notification-history-empty">{t('notificationHistoryEmpty')}</div>
            ) : visibleItems.map(item => (
              <div key={item.id} className={`notification-history-item ${item.type}`}>
                <div className="notification-history-status">
                  {item.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
                </div>
                <div className="notification-history-content">
                  <div className="notification-history-summary-row">
                    <span className={`notification-history-type ${item.type}`}>
                      {item.type === 'success' ? t('notificationFilterSuccess') : t('notificationFilterError')}
                    </span>
                    <span>{formatLocalDateTime(item.created_at, i18n.language)}</span>
                  </div>
                  <div className="notification-history-context">
                    {caseTitle(item) && (
                      <div>
                        <span>{t('caseTitle')}</span>
                        <strong>{shortText(caseTitle(item), 80)}</strong>
                      </div>
                    )}
                    {caseType(item) && (
                      <div>
                        <span>{t('caseType')}</span>
                        <strong>{caseType(item)}</strong>
                      </div>
                    )}
                    <div>
                      <span>{t('notificationCategoryName')}</span>
                      <strong>{notificationCategoryLabel(item.category, i18n.language)}</strong>
                    </div>
                    <div>
                      <span>{t('notificationTypeName')}</span>
                      <strong>{typeName(item, i18n.language)}</strong>
                    </div>
                    <div>
                      <span>{t('notificationObjectName')}</span>
                      <strong>{objectName(item, i18n.language)}</strong>
                    </div>
                  </div>
                  <div className="notification-history-message-label">{t('notificationMessage')}</div>
                  <div className="notification-history-message">{item.message}</div>
                </div>
              </div>
            ))}
          </div>

          <div className="notification-history-footer">
            <button className="btn btn-ghost btn-sm" onClick={clearCurrent} disabled={visibleItems.length === 0}>
              <Trash2 size={14} /> {filter === 'all' ? t('clearAllNotifications') : t('clearCurrentNotifications')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
