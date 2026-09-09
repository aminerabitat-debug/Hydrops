import { useState } from 'react'

import { Modal } from './Modal'

interface NewVariantDialogProps {
  onClose: () => void
  onCreate: (name: string, description: string) => Promise<void>
}

export function NewVariantDialog({ onClose, onCreate }: NewVariantDialogProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')

  const handleConfirm = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError("L'intitulé de la variante est obligatoire.")
      return
    }
    try {
      await onCreate(trimmed, description.trim())
      onClose()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <Modal
      title="Nouvelle variante"
      onClose={onClose}
      error={error}
      confirmLabel="Créer"
      onConfirm={handleConfirm}
      confirmDisabled={!name.trim()}
    >
      <div className="modal-field">
        <label htmlFor="new-variant-name">Nom de la variante</label>
        <input
          id="new-variant-name"
          type="text"
          value={name}
          autoFocus
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleConfirm()}
        />
      </div>
      <div className="modal-field">
        <label htmlFor="new-variant-desc">Description (optionnelle)</label>
        <textarea id="new-variant-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
    </Modal>
  )
}
