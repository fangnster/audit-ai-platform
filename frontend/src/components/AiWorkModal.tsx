import type { ReactNode } from 'react'
import { X } from 'lucide-react'

type AiWorkModalProps = {
  icon?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
  onClose: () => void
  closeTitle?: string
  closeDisabled?: boolean
  accent?: 'primary' | 'gold'
}

export function AiWorkModal({
  icon,
  title,
  subtitle,
  children,
  footer,
  onClose,
  closeTitle = 'Close',
  closeDisabled = false,
  accent = 'primary',
}: AiWorkModalProps) {
  return (
    <div className="ai-work-modal-backdrop" onClick={() => !closeDisabled && onClose()}>
      <div className="ai-work-modal-card fade-up" onClick={(event) => event.stopPropagation()}>
        <div className="ai-work-modal-header">
          <span className={`ai-work-modal-icon ${accent === 'gold' ? 'gold' : ''}`}>{icon}</span>
          <div className="ai-work-modal-title-block">
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            className="btn btn-ghost btn-sm ai-work-modal-close"
            onClick={onClose}
            disabled={closeDisabled}
            title={closeTitle}
            type="button"
          >
            <X size={16} />
          </button>
        </div>
        <div className="ai-work-modal-body">{children}</div>
        {footer && <div className="ai-work-modal-actions">{footer}</div>}
      </div>
    </div>
  )
}
