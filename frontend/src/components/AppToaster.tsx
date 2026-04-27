import { Toaster, ToastBar, resolveValue, type Toast } from 'react-hot-toast'
import type { NotificationHistoryMeta } from '../utils/notificationHistory'

type ToastWithHistoryMeta = Toast & {
  historyMeta?: NotificationHistoryMeta
}

const shortText = (value: string, maxLength = 80) => {
  const text = value.trim()
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function caseContext(meta?: NotificationHistoryMeta) {
  const caseTitle = meta?.case_title?.trim()
  const caseType = meta?.case_type?.trim()
  return [
    caseTitle ? shortText(caseTitle) : '',
    caseType || '',
  ].filter(Boolean)
}

export function AppToaster() {
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
        const context = caseContext(meta)
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
