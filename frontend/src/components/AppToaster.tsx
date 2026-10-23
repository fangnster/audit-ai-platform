import { useTranslation } from 'react-i18next'
import { auditTypeLabel } from '../utils/auditLabels'
import { Toaster, ToastBar, resolveValue, type Toast } from 'react-hot-toast'
import type { NotificationHistoryMeta } from '../utils/notificationHistory'

type ToastWithHistoryMeta = Toast & {
  historyMeta?: NotificationHistoryMeta
}

const shortText = (value: string, maxLength = 80) => {
  const text = value.trim()
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function caseContext(language: string, meta?: NotificationHistoryMeta) {
  const caseTitle = meta?.case_title?.trim()
  const caseType = meta?.case_type?.trim()
  return [
    caseTitle ? shortText(caseTitle) : '',
    auditTypeLabel(caseType || '', language),
  ].filter(Boolean)
}

export function AppToaster() {
  const { i18n } = useTranslation()
  return (
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: 'var(--bg-panel)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
          fontSize: '0.875rem',
        },
      }}
    >
      {(toast) => {
        const meta = (toast as ToastWithHistoryMeta).historyMeta
        const context = caseContext(i18n.language, meta)
        return (
          <ToastBar
            toast={toast}
            position={toast.position || 'top-right'}
            style={{
              minWidth: 280,
              maxWidth: 420,
              padding: '10px 12px',
            }}
          >
            {({ icon }) => (
              <>
                {icon && <span className="app-toast-icon">{icon}</span>}
                <div className="app-toast-content">
                  <div className="app-toast-message" {...toast.ariaProps}>
                    {resolveValue(toast.message, toast)}
                  </div>
                  {context.length > 0 && (
                    <div className="app-toast-case">
                      {context.map(item => <span key={item}>{item}</span>)}
                    </div>
                  )}
                </div>
              </>
            )}
          </ToastBar>
        )
      }}
    </Toaster>
  )
}
