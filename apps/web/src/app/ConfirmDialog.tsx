import { useState } from 'react'

import { Modal } from './Modal'

interface ConfirmDialogProps {
  title: string
  message: string
  confirmLabel: string
  onClose: () => void
  onConfirm: () => Promise<void>
}

export function ConfirmDialog({ title, message, confirmLabel, onClose, onConfirm }: ConfirmDialogProps) {
  const [error, setError] = useState('')

  const handleConfirm = async () => {
    try {
      await onConfirm()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <Modal title={title} onClose={onClose} error={error} confirmLabel={confirmLabel} onConfirm={handleConfirm} danger>
      <p style={{ margin: 0, color: 'var(--text)', fontSize: 14 }}>{message}</p>
    </Modal>
  )
}
