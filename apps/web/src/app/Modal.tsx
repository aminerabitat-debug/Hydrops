// Modale generique (remplace window.prompt/confirm, non supportes dans certains contextes
// embarques — voir docs/architecture, note Lot 1).

import type { ReactNode } from 'react'

interface ModalProps {
  title: string
  onClose: () => void
  children: ReactNode
  error?: string
  confirmLabel: string
  onConfirm: () => void
  confirmDisabled?: boolean
  danger?: boolean
}

export function Modal({ title, onClose, children, error, confirmLabel, onConfirm, confirmDisabled, danger }: ModalProps) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">{title}</div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Fermer">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-error">{error}</div>
        <div className="modal-actions">
          <button type="button" className="modal-btn modal-btn-cancel" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className={`modal-btn ${danger ? 'modal-btn-danger' : 'modal-btn-confirm'}`}
            onClick={onConfirm}
            disabled={confirmDisabled}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
