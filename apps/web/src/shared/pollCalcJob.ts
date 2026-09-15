// Calcul hydraulique asynchrone (job + polling, cf. shared/apiClient.ts:startCalculation/
// getCalculationJobStatus) — factorise la boucle de suivi partagee par les deux points d'appel du
// bouton "Calculer" (App.tsx, ProfileTableView.tsx), meme principe que le polling d'import de
// trace (ProjectTree.tsx:handleImportFile). Gere aussi le dialogue d'estimation (consigne
// utilisateur : "évaluer le temps de calcul estimé au début, et si ça dépasse 30s, demander à
// l'utilisateur s'il veut réduire le nombre de piquets") via `onNeedsConfirmation`, que l'appelant
// implemente (affichage d'une modale) — cette fonction ne connait rien de l'UI.

import { api } from './apiClient'
import type { CalcRunResult } from './types'
import { isCalcNeedsConfirmation } from './types'

const POLL_INTERVAL_MS = 400

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export type CalcConfirmChoice = 'full' | 'reduced' | 'cancel'

export interface RunCalculationJobCallbacks {
  onProgress?: (completed: number, total: number) => void
  onNeedsConfirmation: (estimatedSeconds: number, totalFineSegments: number) => Promise<CalcConfirmChoice>
}

// Retourne le resultat final, ou `null` si l'utilisateur annule depuis le dialogue d'estimation.
export async function runCalculationJob(
  sessionId: string,
  variantId: string,
  scope: { traceId: string; startNodeId: string } | undefined,
  callbacks: RunCalculationJobCallbacks,
): Promise<CalcRunResult | null> {
  let opts: { confirmed?: boolean; reduceResolution?: boolean } | undefined

  for (;;) {
    const started = await api.startCalculation(sessionId, variantId, scope, opts)
    if (isCalcNeedsConfirmation(started)) {
      const choice = await callbacks.onNeedsConfirmation(started.estimated_seconds, started.total_fine_segments)
      if (choice === 'cancel') return null
      opts = { confirmed: true, reduceResolution: choice === 'reduced' }
      continue
    }

    callbacks.onProgress?.(0, started.total_units)
    let job = await api.getCalculationJobStatus(sessionId, variantId, started.job_id)
    while (job.status === 'running') {
      callbacks.onProgress?.(job.completed_units, job.total_units)
      await sleep(POLL_INTERVAL_MS)
      job = await api.getCalculationJobStatus(sessionId, variantId, started.job_id)
    }

    if (job.status === 'failed' || !job.result) {
      throw new Error(job.error ?? 'Échec du calcul')
    }
    callbacks.onProgress?.(job.total_units, job.total_units)
    return job.result
  }
}
