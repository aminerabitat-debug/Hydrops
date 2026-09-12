// Dialogue de creation ET d'edition de noeud (cdc §8) : choix du type (un des ouvrages reels), nom
// pre-rempli (editable), et mise en donnees detaillee specifique au type choisi (cdc §8, consigne
// utilisateur). Le type "Extremite"/terminal n'est plus propose du tout (consigne utilisateur) —
// meme une extremite de trace doit porter un type reel (ex. une station de pompage en bout de
// trace). "Jonction simple (changement de DN/matériau)" n'est plus proposee non plus (consigne
// utilisateur, Lot 3 etape 1d) : ce n'est pas un ouvrage, seuls les ouvrages reels restent
// selectionnables ici — junction ne subsiste que comme type de semis par defaut cote backend pour
// les extremites de trace pas encore affectees (cf. traces.py:seed_terminal_nodes...). La
// suppression d'un noeud se fait desormais uniquement depuis la fenetre principale (icone 🗑 dans
// le tableau/l'arborescence, consigne utilisateur) — plus de bouton "Supprimer" ici, pour eviter
// la redondance entre les deux endroits.

import { useMemo, useState } from 'react'

import { Modal } from '../../app/Modal'
import {
  OUVRAGE_FIELDS,
  TREATMENT_PLANT_SUBTYPES,
  applyFieldDefaults,
  computeReservoirCapacity,
  inheritableOuvrageData,
  type OuvrageFieldSpec,
} from '../../shared/ouvrageFields'
import type { CreatableNodeType, Node } from '../../shared/types'

export interface NodeSubmitPayload {
  type: CreatableNodeType
  name: string
  data: Record<string, unknown>
  injectedFlow: number
  withdrawnFlow: number
}

interface NodeDialogProps {
  mode: 'create' | 'edit'
  pk: number
  existingNodes: Node[]
  initialType?: CreatableNodeType
  initialName?: string | null
  initialData?: Record<string, unknown> | null
  initialInjectedFlow?: number
  initialWithdrawnFlow?: number
  // Id du noeud en cours d'edition — exclu de la verification d'unicite du nom (sinon un noeud
  // dont le nom n'a pas change se heurterait toujours a "lui-meme").
  excludeNodeId?: string
  // Ouvrage reel le plus proche en amont dans le profil (calcule par l'appelant, qui connait la
  // trace/le pk) — sert a preremplir fluide/débit en mode creation (consigne utilisateur). Ignore
  // en mode edition (on ne veut pas ecraser silencieusement une donnee deja saisie).
  precedingOuvrage?: Node | null
  onClose: () => void
  onSubmit: (payload: NodeSubmitPayload) => Promise<void>
}

const TYPE_OPTIONS: { value: CreatableNodeType; label: string; namePrefix: string | null }[] = [
  { value: 'tie_in', label: 'Piquage', namePrefix: 'P' },
  { value: 'pumping_station', label: 'Station de pompage', namePrefix: 'SP' },
  { value: 'storage_reservoir', label: 'Réservoir de stockage', namePrefix: 'Res' },
  { value: 'surge_reservoir', label: 'Réservoir de mise en charge', namePrefix: 'RMC' },
  { value: 'pressure_break', label: 'Brise charge', namePrefix: 'BC' },
  { value: 'treatment_plant', label: 'Station de traitement', namePrefix: 'ST' },
]

const FLOW_DIRECTION_OPTIONS = ['Prélèvement', 'Injection'] as const
type FlowDirection = (typeof FLOW_DIRECTION_OPTIONS)[number]

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

function resolveInitialFlow(
  injected: number,
  withdrawn: number,
): { direction: FlowDirection; value: number } {
  if (withdrawn > 0) return { direction: 'Prélèvement', value: withdrawn }
  if (injected > 0) return { direction: 'Injection', value: injected }
  return { direction: 'Prélèvement', value: 0 }
}

export function NodeDialog({
  mode,
  pk,
  existingNodes,
  initialType,
  initialName,
  initialData,
  initialInjectedFlow,
  initialWithdrawnFlow,
  excludeNodeId,
  precedingOuvrage,
  onClose,
  onSubmit,
}: NodeDialogProps) {
  const [type, setType] = useState<CreatableNodeType>(resolveInitialType(initialType))
  const [name, setName] = useState(initialName ?? '')
  const [data, setData] = useState<Record<string, unknown>>(
    initialData ??
      (mode === 'create'
        ? applyFieldDefaults(
            inheritableOuvrageData(precedingOuvrage?.data, OUVRAGE_FIELDS[resolveInitialType(initialType)]),
            OUVRAGE_FIELDS[resolveInitialType(initialType)],
          )
        : {}),
  )
  const initialFlow = resolveInitialFlow(initialInjectedFlow ?? 0, initialWithdrawnFlow ?? 0)
  const [flowDirection, setFlowDirection] = useState<FlowDirection>(initialFlow.direction)
  const [flowValue, setFlowValue] = useState<number>(initialFlow.value)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const namePrefix = useMemo(() => TYPE_OPTIONS.find((o) => o.value === type)?.namePrefix, [type])
  const fieldSpecs = OUVRAGE_FIELDS[type]
  const reservoirCapacity = useMemo(() => computeReservoirCapacity(data, type), [data, type])
  const selectedSubtype = useMemo(
    () => TREATMENT_PLANT_SUBTYPES.find((s) => s.value === data.plant_subtype),
    [data.plant_subtype],
  )

  const handleTypeChange = (newType: CreatableNodeType) => {
    setType(newType)
    // En edition, ne pas ecraser un nom deja saisi par un simple changement de type dans le select.
    if (mode === 'create') setName(suggestName(newType, existingNodes))
    // Les champs de mise en donnees sont entierement differents d'un type a l'autre — repartir
    // d'un formulaire vierge evite de soumettre des cles d'un autre type par erreur. En creation,
    // reheriter fluide/débit de l'ouvrage precedent pour le NOUVEAU type (consigne utilisateur).
    setData(
      mode === 'create'
        ? applyFieldDefaults(inheritableOuvrageData(precedingOuvrage?.data, OUVRAGE_FIELDS[newType]), OUVRAGE_FIELDS[newType])
        : {},
    )
  }

  const setField = (key: string, value: unknown) => {
    setData((d) => ({ ...d, [key]: value }))
  }

  const handleSubtypeChange = (subtype: string) => {
    // Chaque sous-type de station de traitement a sa propre liste de filieres — repartir d'une
    // selection vierge si on change de sous-type, sinon d'anciennes filieres non pertinentes
    // resteraient cochees silencieusement.
    setData({ plant_subtype: subtype, treated_flow: data.treated_flow, filieres: [] })
  }

  const toggleFiliere = (filiere: string) => {
    const current = Array.isArray(data.filieres) ? (data.filieres as string[]) : []
    const next = current.includes(filiere) ? current.filter((f) => f !== filiere) : [...current, filiere]
    setField('filieres', next)
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
      const injectedFlow = type === 'tie_in' && flowDirection === 'Injection' ? flowValue : 0
      const withdrawnFlow = type === 'tie_in' && flowDirection === 'Prélèvement' ? flowValue : 0
      await onSubmit({ type, name: trimmedName, data, injectedFlow, withdrawnFlow })
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const renderField = (spec: OuvrageFieldSpec) => {
    if (spec.showIf && !spec.showIf(data)) return null
    if (spec.kind === 'select') {
      return (
        <div className="modal-field" key={spec.key}>
          <label htmlFor={`node-field-${spec.key}`}>{spec.label}</label>
          <select
            id={`node-field-${spec.key}`}
            value={(data[spec.key] as string) ?? ''}
            onChange={(e) => setField(spec.key, e.target.value)}
          >
            <option value="" disabled>
              — Choisir —
            </option>
            {spec.options.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </div>
      )
    }
    if (spec.kind === 'number') {
      return (
        <div className="modal-field" key={spec.key}>
          <label htmlFor={`node-field-${spec.key}`}>
            {spec.label}
            {spec.unit ? ` (${spec.unit})` : ''}
          </label>
          <input
            id={`node-field-${spec.key}`}
            type="number"
            value={(data[spec.key] as number) ?? ''}
            onChange={(e) => setField(spec.key, e.target.value === '' ? undefined : Number(e.target.value))}
          />
        </div>
      )
    }
    return null
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

      {type === 'tie_in' && (
        <>
          <div className="modal-field">
            <label htmlFor="node-flow-direction">Prélèvement / Injection</label>
            <select
              id="node-flow-direction"
              value={flowDirection}
              onChange={(e) => setFlowDirection(e.target.value as FlowDirection)}
            >
              {FLOW_DIRECTION_OPTIONS.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          </div>
          <div className="modal-field">
            <label htmlFor="node-flow-value">Débit (m³/h)</label>
            <input
              id="node-flow-value"
              type="number"
              value={flowValue || ''}
              onChange={(e) => setFlowValue(e.target.value === '' ? 0 : Number(e.target.value))}
            />
          </div>
          {flowDirection === 'Prélèvement' && (
            <label className="modal-checkbox-label">
              <input
                type="checkbox"
                checked={data.include_withdrawal_in_sizing !== false}
                onChange={(e) => setField('include_withdrawal_in_sizing', e.target.checked)}
              />
              <span>
                Prendre en compte le débit de ce piquage dans le dimensionnement aval (décocher pour
                dimensionner le tronçon aval sur le débit de tête, sans soustraire ce prélèvement)
              </span>
            </label>
          )}
        </>
      )}

      {fieldSpecs?.map(renderField)}

      {(type === 'storage_reservoir' || type === 'surge_reservoir') && reservoirCapacity != null && (
        <p className="modal-field-hint" style={{ margin: 0 }}>
          Capacité estimée (débit × autonomie) : {reservoirCapacity.toFixed(1)} m³
        </p>
      )}

      {type === 'treatment_plant' && (
        <>
          <div className="modal-field">
            <label htmlFor="node-plant-subtype">Type</label>
            <select
              id="node-plant-subtype"
              value={(data.plant_subtype as string) ?? ''}
              onChange={(e) => handleSubtypeChange(e.target.value)}
            >
              <option value="" disabled>
                — Choisir —
              </option>
              {TREATMENT_PLANT_SUBTYPES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          <div className="modal-field">
            <label htmlFor="node-treated-flow">Débit d'eau traité (m³/h)</label>
            <input
              id="node-treated-flow"
              type="number"
              value={(data.treated_flow as number) ?? ''}
              onChange={(e) => setField('treated_flow', e.target.value === '' ? undefined : Number(e.target.value))}
            />
          </div>
          {selectedSubtype && (
            <div className="modal-field">
              <label>Filières</label>
              <div className="modal-checkbox-group">
                {selectedSubtype.filieres.map((filiere) => (
                  <label key={filiere} className="modal-checkbox-label">
                    <input
                      type="checkbox"
                      checked={Array.isArray(data.filieres) && (data.filieres as string[]).includes(filiere)}
                      onChange={() => toggleFiliere(filiere)}
                    />
                    <span>{filiere}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Modal>
  )
}
