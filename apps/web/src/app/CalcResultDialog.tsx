// Résultat du bouton Calcul > Calculer (consigne utilisateur) : confirmation + alertes du moteur
// hydraulique (segments pour lesquels aucune conduite du catalogue ne respecte toutes les
// contraintes — choix du meilleur compromis disponible, cf. hydrops_engine.hydraulics).
// Sur une alerte hydrostatique gravitaire déplaçable, propose d'accepter/refuser un déplacement
// du réservoir au PK compatible le plus proche (consigne utilisateur) — l'acceptation relance un
// calcul complet (tous les tronçons), pas seulement celui qui a déclenché la suggestion.

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
    <Modal title="Résultat du calcul" onClose={onClose} confirmLabel="Fermer" onConfirm={onClose}>
      <p style={{ margin: 0, color: 'var(--text)', fontSize: 14 }}>
        Calcul terminé : {result.segments_updated} segment(s) et {result.nodes_updated} nœud(s) mis à jour.
      </p>
      {result.alerts.length > 0 ? (
        <>
          <p style={{ margin: 0, color: 'var(--text)', fontSize: 13, fontWeight: 600 }}>
            {result.alerts.length} alerte(s) :
          </p>
          <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--muted)', fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {result.alerts.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </>
      ) : (
        <p style={{ margin: 0, color: 'var(--accent-2)', fontSize: 13 }}>Aucune alerte — toutes les contraintes sont respectées.</p>
      )}
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
