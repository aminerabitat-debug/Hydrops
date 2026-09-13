// Suite du bouton Calcul > Calculer — PLUS le recapitulatif/la liste des alertes (consigne
// utilisateur : ces messages doivent rester restreints a la barre d'etat + au journal, cf.
// state/store.ts:setStatusMessage/LogWindow.tsx, jamais une fenetre qui interrompt apres CHAQUE
// calcul). Cette fenetre ne sert plus qu'aux propositions de repositionnement (App.tsx ne l'ouvre
// que si `reposition_suggestions` en contient au moins une) : sur une alerte hydrostatique
// gravitaire deplacable, propose d'accepter/refuser un deplacement du reservoir au PK compatible
// le plus proche — l'acceptation relance un calcul complet (tous les tronçons), pas seulement
// celui qui a declenche la suggestion.

import { useState } from 'react'

import { Modal } from './Modal'
import type { CalcRunResult, RepositionSuggestion } from '../shared/types'

interface CalcResultDialogProps {
  result: CalcRunResult
  onClose: () => void
  onAcceptReposition: (suggestion: RepositionSuggestion) => Promise<void>
}

export function CalcResultDialog({ result, onClose, onAcceptReposition }: CalcResultDialogProps) {
  const [decidedNodeIds, setDecidedNodeIds] = useState<Set<string>>(new Set())
  const [processingNodeId, setProcessingNodeId] = useState<string | null>(null)

  const handleAccept = async (suggestion: RepositionSuggestion) => {
    setProcessingNodeId(suggestion.node_id)
    try {
      await onAcceptReposition(suggestion)
      // Le composant est remonte avec un nouveau `result` par l'appelant (App.tsx) une fois le
      // calcul complet relance — pas besoin de gerer `decidedNodeIds` ici pour ce cas.
    } finally {
      setProcessingNodeId(null)
    }
  }

  return (
    <Modal title="Repositionnement suggéré" onClose={onClose} confirmLabel="Fermer" onConfirm={onClose}>
      {result.reposition_suggestions
        .filter((s) => !decidedNodeIds.has(s.node_id))
        .map((s) => (
          <div key={s.node_id} className="reposition-suggestion">
            <p style={{ margin: 0, color: 'var(--text)', fontSize: 13 }}>
              Déplacer <strong>{s.node_label}</strong> du PK {Math.round(s.current_pk)} m au PK{' '}
              {Math.round(s.candidate_pk)} m pour respecter la cote hydrostatique ? Le calcul de l'ensemble des
              tronçons sera relancé.
            </p>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                className="modal-btn modal-btn-cancel"
                disabled={processingNodeId === s.node_id}
                onClick={() => setDecidedNodeIds((prev) => new Set(prev).add(s.node_id))}
              >
                Refuser
              </button>
              <button
                type="button"
                className="modal-btn modal-btn-confirm"
                disabled={processingNodeId === s.node_id}
                onClick={() => handleAccept(s)}
              >
                {processingNodeId === s.node_id ? 'Déplacement…' : 'Accepter'}
              </button>
            </div>
          </div>
        ))}
    </Modal>
  )
}
