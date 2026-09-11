// Dialogue de modification des PARAMETRES DE CALCUL d'un troncon (cdc §7/§8, consigne
// utilisateur). Materiau/DN/Classe ne sont PLUS saisis ici (consigne utilisateur) : ce sont des
// informations relatives aux SEGMENTS entre piquets, renseignees au niveau du profil Data, soit
// par le bouton Calculer (moteur hydraulique), soit en correction manuelle apres coup — cf.
// features/table/DataTable.tsx. Cette fenetre ne garde que les parametres hydrauliques necessaires
// au calcul, dont le sous-ensemble affiche depend du regime (gravitaire vs refoulement, cf.
// shared/troncons.ts:tronconRegime — indetermine se voit proposer le meme jeu que gravitaire, un
// troncon pas encore rattache a une station de pompage n'ayant aucune raison de se limiter au
// sous-ensemble refoulement). Un troncon peut regrouper plusieurs segments (jonctions/piquages
// transparents en son sein) — modifier "le troncon" applique donc la MEME valeur a tous ses
// segments (cf. ProjectTree:handleSaveTroncon, un PATCH par segment_id).

import { useMemo, useState } from 'react'

import { Modal } from '../../app/Modal'
import type { TronconRegime } from '../../shared/troncons'

export interface TronconHydraulicValues {
  headFlow?: number
  upstreamWaterLevelMax?: number
  upstreamWaterLevelMin?: number
  // Non-null = la cote correspondante a ete saisie en relatif ("+N") — permet de la recalculer
  // automatiquement si le reservoir est deplace plus tard (consigne utilisateur, cf.
  // shared/apiClient.ts:patchNodePosition). undefined = cote absolue.
  upstreamWaterLevelMaxOffset?: number
  upstreamWaterLevelMinOffset?: number
  minPressure?: number
  downstreamResidualPressure?: number
  maxVelocity?: number
  minVelocity?: number
}

interface TronconDialogProps {
  label: string
  regime: TronconRegime
  initialHydraulics: TronconHydraulicValues
  // Altitude du terrain au noeud de depart du troncon — permet de resoudre une saisie relative
  // "+N" dans les champs de niveau amont (consigne utilisateur). Absente (troncon sans noeud de
  // depart connu) : une saisie "+N" est alors refusee plutot que silencieusement mal interpretee.
  startNodeGroundZ?: number
  onClose: () => void
  onSubmit: (hydraulics: TronconHydraulicValues) => Promise<void>
}

// Une cote de niveau d'eau amont peut etre saisie soit en absolu ("850.5"), soit relative au
// terrain du noeud de depart en prefixant par "+" ("+3" = altitude du terrain + 3 m) — consigne
// utilisateur. Chaine vide -> tout undefined (comme avant) ; un "+" sans terrain connu ou un
// nombre invalide -> tout undefined (mieux que silencieusement mal interpreter la saisie).
// `offset` (non-undefined seulement en mode relatif) est renvoye a part : permet au reservoir
// deplace plus tard de recalculer automatiquement cette cote (consigne utilisateur, cf.
// shared/apiClient.ts:patchNodePosition) — une cote absolue, elle, ne l'est jamais.
function resolveLevelInput(
  raw: string,
  startGroundZ: number | undefined,
): { value: number | undefined; offset: number | undefined } {
  const trimmed = raw.trim()
  if (trimmed === '') return { value: undefined, offset: undefined }
  if (trimmed.startsWith('+')) {
    if (startGroundZ == null) return { value: undefined, offset: undefined }
    const offset = Number(trimmed.slice(1))
    return Number.isFinite(offset) ? { value: startGroundZ + offset, offset } : { value: undefined, offset: undefined }
  }
  const value = Number(trimmed)
  return { value: Number.isFinite(value) ? value : undefined, offset: undefined }
}

// Reaffiche "+N" a la reouverture si la cote avait ete saisie en relatif (offset connu) — sinon
// la cote absolue resolue, telle quelle.
function formatInitialLevel(value: number | undefined, offset: number | undefined): string {
  if (offset != null) return `+${offset}`
  return value?.toString() ?? ''
}

export function TronconDialog({ label, regime, initialHydraulics, startNodeGroundZ, onClose, onSubmit }: TronconDialogProps) {
  const [hydraulics, setHydraulics] = useState<TronconHydraulicValues>(initialHydraulics)
  const [rawUpstreamMax, setRawUpstreamMax] = useState(
    formatInitialLevel(initialHydraulics.upstreamWaterLevelMax, initialHydraulics.upstreamWaterLevelMaxOffset),
  )
  const [rawUpstreamMin, setRawUpstreamMin] = useState(
    formatInitialLevel(initialHydraulics.upstreamWaterLevelMin, initialHydraulics.upstreamWaterLevelMinOffset),
  )
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const setHydraulicField = (key: keyof TronconHydraulicValues, value: string) => {
    setHydraulics((h) => ({ ...h, [key]: value === '' ? undefined : Number(value) }))
  }

  const resolvedMax = useMemo(() => resolveLevelInput(rawUpstreamMax, startNodeGroundZ), [rawUpstreamMax, startNodeGroundZ])
  const resolvedMin = useMemo(() => resolveLevelInput(rawUpstreamMin, startNodeGroundZ), [rawUpstreamMin, startNodeGroundZ])

  const handleConfirm = async () => {
    setSubmitting(true)
    setError('')
    try {
      await onSubmit({
        ...hydraulics,
        upstreamWaterLevelMax: resolvedMax.value,
        upstreamWaterLevelMaxOffset: resolvedMax.offset,
        upstreamWaterLevelMin: resolvedMin.value,
        upstreamWaterLevelMinOffset: resolvedMin.offset,
      })
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const isGravitaire = regime !== 'refoulement'
  // Au minimum de quoi lancer un calcul plus tard (consigne utilisateur : le troncon passe "au
  // vert"/valide des qu'on enregistre) — le debit de tete (commun aux deux regimes), plus le
  // niveau amont en gravitaire ou la residuelle aval en refoulement.
  const hasMinimumData =
    hydraulics.headFlow != null &&
    (isGravitaire
      ? resolvedMax.value != null && resolvedMin.value != null
      : hydraulics.downstreamResidualPressure != null)

  return (
    <Modal
      title={`Tronçon ${label}`}
      onClose={onClose}
      error={error}
      confirmLabel="Enregistrer"
      onConfirm={handleConfirm}
      confirmDisabled={submitting || !hasMinimumData}
    >
      <div className="modal-field">
        <label htmlFor="troncon-head-flow">Débit (m³/h)</label>
        <input
          id="troncon-head-flow"
          type="number"
          value={hydraulics.headFlow ?? ''}
          onChange={(e) => setHydraulicField('headFlow', e.target.value)}
        />
      </div>
      {isGravitaire && (
        <>
          <div className="modal-field">
            <label htmlFor="troncon-upstream-max">Niveau du plan d'eau amont max (m)</label>
            <input
              id="troncon-upstream-max"
              type="text"
              inputMode="decimal"
              placeholder="ex : 850 ou +3"
              value={rawUpstreamMax}
              onChange={(e) => setRawUpstreamMax(e.target.value)}
            />
            <span className="modal-field-hint">Cote absolue, ou +N pour N m au-dessus du terrain au départ.</span>
          </div>
          <div className="modal-field">
            <label htmlFor="troncon-upstream-min">Niveau du plan d'eau amont min (m)</label>
            <input
              id="troncon-upstream-min"
              type="text"
              inputMode="decimal"
              placeholder="ex : 850 ou +3"
              value={rawUpstreamMin}
              onChange={(e) => setRawUpstreamMin(e.target.value)}
            />
            <span className="modal-field-hint">Cote absolue, ou +N pour N m au-dessus du terrain au départ.</span>
          </div>
        </>
      )}
      <div className="modal-field">
        <label htmlFor="troncon-min-pressure">Pression min (m)</label>
        <input
          id="troncon-min-pressure"
          type="number"
          value={hydraulics.minPressure ?? ''}
          onChange={(e) => setHydraulicField('minPressure', e.target.value)}
        />
      </div>
      <div className="modal-field">
        <label htmlFor="troncon-residual-pressure">Pression résiduelle aval (m)</label>
        <input
          id="troncon-residual-pressure"
          type="number"
          value={hydraulics.downstreamResidualPressure ?? ''}
          onChange={(e) => setHydraulicField('downstreamResidualPressure', e.target.value)}
        />
      </div>
      <div className="modal-field">
        <label htmlFor="troncon-max-velocity">Vitesse Max (m/s)</label>
        <input
          id="troncon-max-velocity"
          type="number"
          value={hydraulics.maxVelocity ?? ''}
          onChange={(e) => setHydraulicField('maxVelocity', e.target.value)}
        />
      </div>
      <div className="modal-field">
        <label htmlFor="troncon-min-velocity">Vitesse Min (m/s)</label>
        <input
          id="troncon-min-velocity"
          type="number"
          value={hydraulics.minVelocity ?? ''}
          onChange={(e) => setHydraulicField('minVelocity', e.target.value)}
        />
        <span className="modal-field-hint">
          Gravitaire : plafonne l'augmentation du DN tentée pour résoudre un défaut de pression.
        </span>
      </div>
    </Modal>
  )
}
