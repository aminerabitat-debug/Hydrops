// Ajout/edition d'une traversee manuelle depuis la carte (consigne utilisateur) — meme famille que
// NodeDialog.tsx (features/profile/NodeDialog.tsx) : un petit formulaire, PK modifiable (recalcule
// lon/lat cote serveur, cf. routers/traces.py:patch_crossing), type + libelle optionnel. La
// suppression n'est proposee qu'en edition (bouton secondaire "Supprimer", jamais en creation).

import { useState } from 'react'

import { Modal } from '../../app/Modal'
import { crossingKindLabel } from '../../shared/crossingColors'
import type { CrossingKind } from '../../shared/types'

const KIND_OPTIONS: CrossingKind[] = ['highway', 'railway', 'waterway', 'building', 'urban', 'forest']

export interface CrossingSubmitPayload {
  kind: CrossingKind
  pk: number
  label?: string
}

interface CrossingDialogProps {
  mode: 'create' | 'edit'
  initialPk: number
  initialKind?: CrossingKind
  initialLabel?: string | null
  onClose: () => void
  onSubmit: (payload: CrossingSubmitPayload) => Promise<void>
  onDelete?: () => Promise<void>
}

export function CrossingDialog({
  mode,
  initialPk,
  initialKind,
  initialLabel,
  onClose,
  onSubmit,
  onDelete,
}: CrossingDialogProps) {
  const [kind, setKind] = useState<CrossingKind>(initialKind ?? 'highway')
  const [pk, setPk] = useState(initialPk)
  const [label, setLabel] = useState(initialLabel ?? '')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleConfirm = async () => {
    setSubmitting(true)
    setError('')
    try {
      await onSubmit({ kind, pk, label: label.trim() || undefined })
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async () => {
    if (!onDelete) return
    setDeleting(true)
    setError('')
    try {
      await onDelete()
      onClose()
    } catch (e) {
      setError((e as Error).message)
      setDeleting(false)
    }
  }

  return (
    <Modal
      title={mode === 'create' ? `Ajouter une traversée au PK ${Math.round(initialPk)} m` : 'Modifier la traversée'}
      onClose={onClose}
      error={error}
      confirmLabel={mode === 'create' ? 'Ajouter' : 'Enregistrer'}
      onConfirm={handleConfirm}
      confirmDisabled={submitting || deleting}
      secondaryLabel={mode === 'edit' && onDelete ? 'Supprimer' : undefined}
      onSecondary={mode === 'edit' && onDelete ? handleDelete : undefined}
      secondaryDisabled={submitting || deleting}
    >
      <div className="modal-field">
        <label htmlFor="crossing-kind">Type</label>
        <select id="crossing-kind" value={kind} onChange={(e) => setKind(e.target.value as CrossingKind)}>
          {KIND_OPTIONS.map((k) => (
            <option key={k} value={k}>
              {crossingKindLabel(k)}
            </option>
          ))}
        </select>
      </div>
      <div className="modal-field">
        <label htmlFor="crossing-pk">PK (m)</label>
        <input
          id="crossing-pk"
          type="number"
          value={pk}
          onChange={(e) => setPk(Number(e.target.value))}
        />
      </div>
      <div className="modal-field">
        <label htmlFor="crossing-label">Libellé (optionnel)</label>
        <input
          id="crossing-label"
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="ex. N7, Oued Souss…"
          autoFocus
        />
      </div>
    </Modal>
  )
}
