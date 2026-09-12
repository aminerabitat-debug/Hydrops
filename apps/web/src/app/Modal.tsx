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
  // Fenetres a contenu plus riche (tableaux, formulaires a plusieurs sections — Conduites,
  // Preferences, consigne utilisateur) : carte plus large que le formulaire de saisie standard.
  wide?: boolean
  // Action intermediaire optionnelle (ex. "Réinitialiser" dans la fenêtre Conduites, consigne
  // utilisateur : revenir à la config initiale sans fermer la fenêtre) — rendue entre Annuler et
  // le bouton de confirmation.
  secondaryLabel?: string
  onSecondary?: () => void
  secondaryDisabled?: boolean
}

export function Modal({
  title,
  onClose,
  children,
  error,
  confirmLabel,
  onConfirm,
  confirmDisabled,
  danger,
  wide,
  secondaryLabel,
  onSecondary,
  secondaryDisabled,
}: ModalProps) {
  // Consigne utilisateur : "éviter que les fenêtres ne disparaissent lorsqu'on clique en dehors de
  // leur cadre" — le clic sur le fond n'appelle plus onClose (fermeture uniquement via ×/Annuler/
  // confirmation), pour ne jamais perdre une saisie en cours par un clic accidentel a cote.
  return (
    <div className="modal-backdrop">
      <div className={`modal-card ${wide ? 'modal-card--wide' : ''}`}>
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
          {secondaryLabel && onSecondary && (
            <button type="button" className="modal-btn modal-btn-cancel" onClick={onSecondary} disabled={secondaryDisabled}>
              {secondaryLabel}
            </button>
          )}
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
