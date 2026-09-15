// Dialogue d'estimation avant un calcul potentiellement long (consigne utilisateur : "évaluer le
// temps de calcul estimé au début, et si ça dépasse 30s, demander à l'utilisateur s'il veut
// réduire le nombre de piquets" — remplace un plafond fixe arbitraire). Encapsule le pont entre la
// promesse attendue par `runCalculationJob` (shared/pollCalcJob.ts) et l'etat React d'une modale :
// `useCalcConfirmDialog()` renvoie a la fois le noeud a rendre et le callback a passer tel quel.

import { useCallback, useState } from 'react'

import type { CalcConfirmChoice } from '../shared/pollCalcJob'
import { Modal } from './Modal'

interface PendingConfirmation {
  estimatedSeconds: number
  totalFineSegments: number
  resolve: (choice: CalcConfirmChoice) => void
}

export function useCalcConfirmDialog() {
  const [pending, setPending] = useState<PendingConfirmation | null>(null)

  const onNeedsConfirmation = useCallback(
    (estimatedSeconds: number, totalFineSegments: number): Promise<CalcConfirmChoice> =>
      new Promise<CalcConfirmChoice>((resolve) => {
        setPending({ estimatedSeconds, totalFineSegments, resolve })
      }),
    [],
  )

  const respond = (choice: CalcConfirmChoice) => {
    pending?.resolve(choice)
    setPending(null)
  }

  const dialog = pending ? (
    <Modal
      title="Calcul potentiellement long"
      onClose={() => respond('cancel')}
      confirmLabel={`Continuer en pleine résolution (~${Math.round(pending.estimatedSeconds)} s)`}
      onConfirm={() => respond('full')}
      secondaryLabel="Réduire la résolution (~200 m)"
      onSecondary={() => respond('reduced')}
    >
      <p>
        À pleine résolution DEM (~20 m), ce calcul porte sur {pending.totalFineSegments} piquets fins
        et est estimé à environ {Math.round(pending.estimatedSeconds)} secondes.
      </p>
      <p>Continuer en pleine résolution, ou réduire le nombre de piquets pour aller plus vite ?</p>
    </Modal>
  ) : null

  return { dialog, onNeedsConfirmation }
}
