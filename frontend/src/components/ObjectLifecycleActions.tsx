import { AlertTriangle, RotateCcw, Trash2, X } from 'lucide-react'
import type { MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'

export type ConfirmActionKind = 'trash' | 'permanent'

type LifecycleActionsProps = {
  mode: 'active' | 'trash'
  onTrash: () => void
  onRestore: () => void
  onPermanentDelete: () => void
  stopPropagation?: boolean
}

export function ObjectLifecycleActions({
  mode,
  onTrash,
  onRestore,
  onPermanentDelete,
  stopPropagation = false,
}: LifecycleActionsProps) {
  const { t } = useTranslation()
  const handle = (event: MouseEvent, action: () => void) => {
    if (stopPropagation) event.stopPropagation()
    action()
  }

  if (mode === 'trash') {
    return (
      <div className="object-actions">
        <button
          className="btn btn-ghost btn-sm object-action-restore object-icon-button"
          onClick={(event) => handle(event, onRestore)}
          aria-label={t('restore')}
        >
          <RotateCcw size={13} />
        </button>
        <button
          className="btn btn-ghost btn-sm object-action-danger object-icon-button"
          onClick={(event) => handle(event, onPermanentDelete)}
          aria-label={t('permanentDelete')}
        >
          <Trash2 size={13} />
        </button>
      </div>
    )
  }

  return (
    <div className="object-actions">
      <button
        className="btn btn-ghost btn-sm object-action-danger object-icon-button"
        onClick={(event) => handle(event, onTrash)}
        aria-label={t('moveToTrash')}
      >
        <Trash2 size={13} />
      </button>
    </div>
  )
}

type ConfirmActionModalProps = {
  action: ConfirmActionKind
  itemName: string
  itemType: string
  isPending?: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ConfirmActionModal({
  action,
  itemName,
  itemType,
  isPending = false,
  onCancel,
  onConfirm,
}: ConfirmActionModalProps) {
  const { t } = useTranslation()
  const isPermanent = action === 'permanent'
  const title = isPermanent ? t('deleteItemTitle', { type: itemType }) : t('trashItemTitle')
  const description = isPermanent
    ? t('deleteItemDescription', { name: itemName })
    : t('trashItemDescription', { name: itemName })
  const confirmLabel = isPermanent ? t('permanentDelete') : t('moveToTrash')

  return (
    <div className="confirm-modal-backdrop" onClick={onCancel}>
      <div className="confirm-modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="confirm-modal-header">
          <span className={isPermanent ? 'confirm-icon danger' : 'confirm-icon'}>
            <AlertTriangle size={18} />
          </span>
          <div>
            <h2>{title}</h2>
            <p>{description}</p>
          </div>
          <button className="btn btn-ghost btn-sm confirm-close" onClick={onCancel} disabled={isPending}>
            <X size={16} />
          </button>
        </div>
        <div className="confirm-modal-actions">
          <button className="btn btn-ghost" onClick={onCancel} disabled={isPending}>{t('cancel')}</button>
          <button className={isPermanent ? 'btn btn-danger' : 'btn btn-primary'} onClick={onConfirm} disabled={isPending}>
            {isPending ? <span className="spinner" /> : <Trash2 size={14} />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
