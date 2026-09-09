// Dialogue de creation ET d'edition de noeud (cdc §8) : choix du type (un des ouvrages reels) et
// nom pre-rempli (editable). Le type "Extremite"/terminal n'est plus propose du tout (consigne
// utilisateur) — meme une extremite de trace doit porter un type reel (ex. une station de pompage
// en bout de trace). "Jonction simple (changement de DN/matériau)" n'est plus proposee non plus
// (consigne utilisateur, Lot 3 etape 1d) : ce n'est pas un ouvrage, seuls les ouvrages reels
// restent selectionnables ici — junction ne subsiste que comme type de semis par defaut cote
// backend pour les extremites de trace pas encore affectees (cf. traces.py:seed_terminal_nodes...).
// Seule la suppression reste indisponible pour une extremite structurelle (bouton absent si
// `onDelete` n'est pas fourni ; la protection reste basee sur le PK, pas sur le type — cf.
// ProfileTableView/DataTable:isStructuralEndpoint). La mise en donnees detaillee par ouvrage
// (cdc §8) arrive plus tard — ici on ne fait que taguer le type/nom.

import { useMemo, useState } from 'react'

import { Modal } from '../../app/Modal'
import type { CreatableNodeType, Node } from '../../shared/types'

interface NodeDialogProps {
  mode: 'create' | 'edit'
  pk: number
  existingNodes: Node[]
  initialType?: CreatableNodeType
  initialName?: string | null
  // Id du noeud en cours d'edition — exclu de la verification d'unicite du nom (sinon un noeud
  // dont le nom n'a pas change se heurterait toujours a "lui-meme").
  excludeNodeId?: string
  onClose: () => void
  onSubmit: (type: CreatableNodeType, name: string) => Promise<void>
  onDelete?: () => Promise<void>
}

const TYPE_OPTIONS: { value: CreatableNodeType; label: string; namePrefix: string | null }[] = [
  { value: 'tie_in', label: 'Piquage', namePrefix: 'P' },
  { value: 'pumping_station', label: 'Station de pompage', namePrefix: 'SP' },
  { value: 'reservoir', label: 'Réservoir', namePrefix: 'Res' },
  { value: 'pressure_break', label: 'Brise charge', namePrefix: 'BC' },
  { value: 'treatment_plant', label: 'Station de traitement', namePrefix: 'ST' },
]

// Un noeud existant peut encore etre 'junction' (semis par defaut d'une extremite de trace pas
// encore affectee) : ce type n'etant plus dans TYPE_OPTIONS, on retombe sur le premier ouvrage reel
// de la liste au lieu d'un <select> sans option correspondante.
function resolveInitialType(initialType: CreatableNodeType | undefined): CreatableNodeType {
  if (initialType && TYPE_OPTIONS.some((o) => o.value === initialType)) return initialType
  return TYPE_OPTIONS[0].value
}

function suggestName(type: CreatableNodeType, existingNodes: Node[]): string {
  const option = TYPE_OPTIONS.find((o) => o.value === type)
  if (!option?.namePrefix) return ''
  const count = existingNodes.filter((n) => n.type === type).length
  return `${option.namePrefix}${count + 1}`
}

export function NodeDialog({
  mode,
  pk,
  existingNodes,
  initialType,
  initialName,
  excludeNodeId,
  onClose,
  onSubmit,
  onDelete,
}: NodeDialogProps) {
  const [type, setType] = useState<CreatableNodeType>(resolveInitialType(initialType))
  const [name, setName] = useState(initialName ?? '')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const namePrefix = useMemo(() => TYPE_OPTIONS.find((o) => o.value === type)?.namePrefix, [type])

  const handleTypeChange = (newType: CreatableNodeType) => {
    setType(newType)
    // En edition, ne pas ecraser un nom deja saisi par un simple changement de type dans le select.
    if (mode === 'create') setName(suggestName(newType, existingNodes))
  }

  const handleConfirm = async () => {
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('Le nom du nœud est obligatoire.')
      return
    }
    const isDuplicate = existingNodes.some(
      (n) => n.id !== excludeNodeId && (n.name ?? '').trim().toLowerCase() === trimmedName.toLowerCase(),
    )
    if (isDuplicate) {
      setError(`Le nom "${trimmedName}" est déjà utilisé par un autre nœud — choisissez-en un autre.`)
      return
    }
    setSubmitting(true)
    setError('')
    try {
      await onSubmit(type, trimmedName)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async () => {
    if (!onDelete) return
    setSubmitting(true)
    setError('')
    try {
      await onDelete()
      onClose()
    } catch (e) {
      setError((e as Error).message)
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={mode === 'create' ? `Ajouter un nœud au PK ${Math.round(pk)} m` : `Nœud au PK ${Math.round(pk)} m`}
      onClose={onClose}
      error={error}
      confirmLabel={mode === 'create' ? 'Ajouter' : 'Enregistrer'}
      onConfirm={handleConfirm}
      confirmDisabled={submitting || !name.trim()}
    >
      <div className="modal-field">
        <label htmlFor="node-type">Type de nœud</label>
        <select id="node-type" value={type} onChange={(e) => handleTypeChange(e.target.value as CreatableNodeType)}>
          {TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      {namePrefix != null && (
        <div className="modal-field">
          <label htmlFor="node-name">Nom *</label>
          <input
            id="node-name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </div>
      )}
      {mode === 'edit' && onDelete && (
        <button type="button" className="modal-inline-danger" onClick={handleDelete} disabled={submitting}>
          Supprimer ce nœud
        </button>
      )}
    </Modal>
  )
}
