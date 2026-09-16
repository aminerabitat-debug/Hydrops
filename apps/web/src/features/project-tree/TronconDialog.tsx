// Dialogue de modification des PARAMETRES DE CALCUL d'un troncon (cdc §7/§8, consigne
// utilisateur). Materiau/DN/Classe ne sont PLUS saisis en un bloc unique ici : le panneau
// "Contraintes" (matériau/DN/classe PAR PLAGE DE PK, consigne utilisateur) remplace l'ancien
// forçage unique forced_material/forced_dn — un forçage "tout le tronçon" est desormais juste une
// contrainte sans PK de debut/fin. Les autres parametres restent des parametres hydrauliques
// necessaires au calcul, dont le sous-ensemble affiche depend du regime (gravitaire vs
// refoulement, cf. shared/troncons.ts:tronconRegime). Un troncon peut regrouper plusieurs segments
// (jonctions/piquages transparents en son sein) — modifier "le troncon" applique donc la MEME
// valeur/liste de contraintes a tous ses segments (cf. ProjectTree:handleSaveTroncon).

import { useMemo, useState } from 'react'

import { Modal } from '../../app/Modal'
import { api } from '../../shared/apiClient'
import { listPhaseOptions } from '../../shared/phasing'
import { useAppStore } from '../../state/store'
import type { PipeCatalogRow, Project, SegmentConstraint } from '../../shared/types'
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
  // Zone d'exclusion de la contrainte de pression min, en METRES depuis l'ouvrage de depart,
  // propre a ce tronçon (consigne utilisateur) — pre-remplie par l'appelant (ProjectTree.tsx)
  // depuis le pourcentage des Preferences, mais modifiable independamment ici.
  minPressureExclusionM?: number
  maxVelocity?: number
  minVelocity?: number
  // Ancien forçage unique (consigne utilisateur : remplace par le panneau "Contraintes" ci-dessous
  // pour la SAISIE — ces deux champs restent lus par le moteur pour compatibilite ascendante sur
  // un projet deja enregistre, cf. hydrops_api.routers.network:_effective_constraints). Plus
  // jamais ecrits depuis cette fenetre : toujours renvoyes tels quels (inchanges) a la sauvegarde.
  forcedMaterial?: string
  forcedDn?: number
  // Phase de realisation du tronçon entier (consigne utilisateur, volet "Phasage") — distincte du
  // phase_id porte par une SegmentConstraint individuelle (une contrainte ponctuelle peut avoir sa
  // propre phase, independamment de celle du tronçon).
  phaseId?: string | null
}

interface TronconDialogProps {
  label: string
  regime: TronconRegime
  initialHydraulics: TronconHydraulicValues
  // Altitude du terrain au noeud de depart du troncon — permet de resoudre une saisie relative
  // "+N" dans les champs de niveau amont (consigne utilisateur). Absente (troncon sans noeud de
  // depart connu) : une saisie "+N" est alors refusee plutot que silencieusement mal interpretee.
  startNodeGroundZ?: number
  // Catalogue "Conduites" (menu Base de données) — peuple les listes Materiau/DN/Classe du
  // panneau Contraintes, filtre aux lignes actives.
  pipeCatalog: PipeCatalogRow[]
  // Projet courant — le volet "Phasage" (liste deroulante de phase) n'est propose que si
  // project.phasing_enabled (consigne utilisateur, cf. NodeDialog pour le meme principe).
  project?: Project | null
  // Panneau "Contraintes" (consigne utilisateur) : sauvegarde IMMEDIATE (pas dependante du bouton
  // Enregistrer, comme l'homogeneisation du profil graphique) — chaque ajout/edition/suppression
  // appelle directement l'API et broadcast la meme liste a tous les segments reels du tronçon
  // (meme convention que les parametres hydrauliques).
  sessionId: string
  variantId: string
  segmentIds: string[]
  initialConstraints: SegmentConstraint[]
  onConstraintsSaved: () => void
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

// Brouillon d'une contrainte en cours d'ajout/edition (chaines pour les champs numeriques —
// permet un champ vide pendant la saisie, converti a l'enregistrement).
interface ConstraintDraft {
  id?: string
  material: string
  dn: string
  pressureClass: string
  pkStart: string
  pkEnd: string
}

const EMPTY_DRAFT: ConstraintDraft = { material: '', dn: '', pressureClass: '', pkStart: '', pkEnd: '' }

export function TronconDialog({
  label,
  regime,
  initialHydraulics,
  startNodeGroundZ,
  pipeCatalog,
  project,
  sessionId,
  variantId,
  segmentIds,
  initialConstraints,
  onConstraintsSaved,
  onClose,
  onSubmit,
}: TronconDialogProps) {
  const [hydraulics, setHydraulics] = useState<TronconHydraulicValues>(initialHydraulics)
  // Valeurs par defaut +3 m / +1 m (consigne utilisateur) pour un troncon GRAVITAIRE qui n'a
  // encore aucune cote hydrostatique enregistree — un troncon deja renseigne (absolu ou "+N")
  // garde sa vraie valeur, ce defaut ne s'applique qu'a la creation.
  const isGravitaireForDefaults = regime !== 'refoulement'
  const [rawUpstreamMax, setRawUpstreamMax] = useState(
    formatInitialLevel(initialHydraulics.upstreamWaterLevelMax, initialHydraulics.upstreamWaterLevelMaxOffset) ||
      (isGravitaireForDefaults ? '+3' : ''),
  )
  const [rawUpstreamMin, setRawUpstreamMin] = useState(
    formatInitialLevel(initialHydraulics.upstreamWaterLevelMin, initialHydraulics.upstreamWaterLevelMinOffset) ||
      (isGravitaireForDefaults ? '+1' : ''),
  )
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const [constraints, setConstraints] = useState<SegmentConstraint[]>(initialConstraints)
  const [draft, setDraft] = useState<ConstraintDraft | null>(null)
  const [constraintError, setConstraintError] = useState('')
  const [savingConstraints, setSavingConstraints] = useState(false)
  const [existingDraft, setExistingDraft] = useState<ConstraintDraft | null>(null)

  const phasingEnabled = project?.phasing_enabled ?? false
  const [phaseId, setPhaseId] = useState(initialHydraulics.phaseId ?? '')

  const pkPickResolver = useAppStore((s) => s.pkPickResolver)
  const beginPkPick = useAppStore((s) => s.beginPkPick)
  const cancelPkPick = useAppStore((s) => s.cancelPkPick)

  const setHydraulicField = (key: keyof TronconHydraulicValues, value: string) => {
    setHydraulics((h) => ({ ...h, [key]: value === '' ? undefined : Number(value) }))
  }

  const resolvedMax = useMemo(() => resolveLevelInput(rawUpstreamMax, startNodeGroundZ), [rawUpstreamMax, startNodeGroundZ])
  const resolvedMin = useMemo(() => resolveLevelInput(rawUpstreamMin, startNodeGroundZ), [rawUpstreamMin, startNodeGroundZ])

  const activeMaterials = useMemo(() => [...new Set(pipeCatalog.filter((r) => r.active).map((r) => r.material))].sort(), [pipeCatalog])
  const dnsForMaterial = useMemo(() => {
    if (!draft?.material) return [...new Set(pipeCatalog.filter((r) => r.active).map((r) => r.dn))].sort((a, b) => a - b)
    return [...new Set(pipeCatalog.filter((r) => r.active && r.material === draft.material).map((r) => r.dn))].sort((a, b) => a - b)
  }, [pipeCatalog, draft?.material])
  const classesForSelection = useMemo(() => {
    let rows = pipeCatalog.filter((r) => r.active)
    if (draft?.material) rows = rows.filter((r) => r.material === draft.material)
    if (draft?.dn) rows = rows.filter((r) => r.dn === Number(draft.dn))
    return [...new Set(rows.map((r) => r.pressure_class))].sort()
  }, [pipeCatalog, draft?.material, draft?.dn])

  const dnsForExistingMaterial = useMemo(() => {
    if (!existingDraft?.material) return [...new Set(pipeCatalog.filter((r) => r.active).map((r) => r.dn))].sort((a, b) => a - b)
    return [...new Set(pipeCatalog.filter((r) => r.active && r.material === existingDraft.material).map((r) => r.dn))].sort((a, b) => a - b)
  }, [pipeCatalog, existingDraft?.material])
  const classesForExistingSelection = useMemo(() => {
    let rows = pipeCatalog.filter((r) => r.active)
    if (existingDraft?.material) rows = rows.filter((r) => r.material === existingDraft.material)
    if (existingDraft?.dn) rows = rows.filter((r) => r.dn === Number(existingDraft.dn))
    return [...new Set(rows.map((r) => r.pressure_class))].sort()
  }, [pipeCatalog, existingDraft?.material, existingDraft?.dn])

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
        phaseId: phasingEnabled ? phaseId || null : hydraulics.phaseId,
      })
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  // Sauvegarde immediate (consigne utilisateur) : broadcast la MEME liste a tous les segments
  // reels du tronçon (meme convention que les parametres hydrauliques ci-dessus), puis adopte la
  // liste renvoyee par le serveur (ids assignes serveur pour une contrainte nouvellement ajoutee).
  // Renvoie true en cas de succes / false en cas d'erreur (422 de contradiction, etc.) — les
  // appelants s'en servent pour savoir s'ils doivent refermer LEUR brouillon (Contraintes vs
  // Éléments existants partagent cette fonction mais pas le meme etat de brouillon).
  const saveConstraints = async (next: (Omit<SegmentConstraint, 'id'> & { id?: string })[]): Promise<boolean> => {
    setSavingConstraints(true)
    setConstraintError('')
    try {
      const results = await Promise.all(segmentIds.map((id) => api.putSegmentConstraints(sessionId, variantId, id, next)))
      setConstraints(results[0]?.constraints ?? [])
      onConstraintsSaved()
      setDraft(null)
      return true
    } catch (e) {
      setConstraintError((e as Error).message)
      return false
    } finally {
      setSavingConstraints(false)
    }
  }

  const handleAddConstraintClick = () => setDraft(EMPTY_DRAFT)
  const handleEditConstraintClick = (c: SegmentConstraint) => {
    if (c.is_existing) return // modifiable uniquement depuis le panneau "Éléments existants" (pas encore implémenté)
    setDraft({
      id: c.id,
      material: c.material ?? '',
      dn: c.dn != null ? String(c.dn) : '',
      pressureClass: c.pressure_class ?? '',
      pkStart: c.pk_start != null ? String(c.pk_start) : '',
      pkEnd: c.pk_end != null ? String(c.pk_end) : '',
    })
  }
  const handleDeleteConstraint = (id: string) => saveConstraints(constraints.filter((c) => c.id !== id))
  const handleClearAllConstraints = () => saveConstraints(constraints.filter((c) => c.is_existing))

  const handleSaveDraft = () => {
    if (!draft) return
    const entry: Omit<SegmentConstraint, 'id'> & { id?: string } = {
      id: draft.id,
      material: draft.material || null,
      dn: draft.dn ? Number(draft.dn) : null,
      pressure_class: draft.pressureClass || null,
      pk_start: draft.pkStart ? Number(draft.pkStart) : null,
      pk_end: draft.pkEnd ? Number(draft.pkEnd) : null,
      is_existing: false,
      phase_id: null,
      source: 'manual',
    }
    const next = draft.id ? constraints.map((c) => (c.id === draft.id ? entry : c)) : [...constraints, entry]
    saveConstraints(next)
  }

  // Volet "Éléments existants" (consigne utilisateur) : meme forme que "Contraintes" mais
  // Matériau/DN/Classe sont TOUS obligatoires (une conduite existante est entièrement connue,
  // contrairement a une contrainte de dimensionnement qui peut ne fixer qu'un champ). Une fois
  // enregistré, l'élément apparait AUSSI dans le tableau "Contraintes" (grisé, is_existing=true —
  // deja gere par ce tableau) mais n'est modifiable/supprimable que depuis CE volet.
  const existingElements = useMemo(() => constraints.filter((c) => c.is_existing), [constraints])
  const handleAddExistingClick = () => setExistingDraft(EMPTY_DRAFT)
  const handleEditExistingClick = (c: SegmentConstraint) => {
    setExistingDraft({
      id: c.id,
      material: c.material ?? '',
      dn: c.dn != null ? String(c.dn) : '',
      pressureClass: c.pressure_class ?? '',
      pkStart: c.pk_start != null ? String(c.pk_start) : '',
      pkEnd: c.pk_end != null ? String(c.pk_end) : '',
    })
  }
  const handleDeleteExisting = (id: string) => saveConstraints(constraints.filter((c) => c.id !== id))

  const handleSaveExistingDraft = () => {
    if (!existingDraft) return
    if (!existingDraft.material || !existingDraft.dn || !existingDraft.pressureClass) {
      setConstraintError("Élément existant : Matériau, DN et Classe sont obligatoires.")
      return
    }
    const entry: Omit<SegmentConstraint, 'id'> & { id?: string } = {
      id: existingDraft.id,
      material: existingDraft.material,
      dn: Number(existingDraft.dn),
      pressure_class: existingDraft.pressureClass,
      pk_start: existingDraft.pkStart ? Number(existingDraft.pkStart) : null,
      pk_end: existingDraft.pkEnd ? Number(existingDraft.pkEnd) : null,
      is_existing: true,
      phase_id: null,
      source: 'existing',
    }
    const next = existingDraft.id
      ? constraints.map((c) => (c.id === existingDraft.id ? entry : c))
      : [...constraints, entry]
    saveConstraints(next).then((ok) => {
      if (ok) setExistingDraft(null)
    })
  }

  // Le PK recu ici est deja accroche au piquet DEM regulier le plus proche (consigne utilisateur,
  // cf. shared/geo.ts:snapPkToNearestSample, applique par MapView/ProfileChart avant de resoudre)
  // — ne PAS arrondir de nouveau ici, un arrondi au metre casserait cet accrochage exact.
  const handlePickExistingPk = (field: 'pkStart' | 'pkEnd') => {
    beginPkPick((pk) => setExistingDraft((d) => (d ? { ...d, [field]: String(pk) } : d)))
  }

  // Bouton "…" (consigne utilisateur) : ferme temporairement CETTE fenetre (masquee via `hidden`
  // ci-dessous, l'etat React — dont le brouillon en cours — est conserve, pas demonte), attend un
  // clic sur la carte/le profil graphique/le profil Data (cf. store.pkPickResolver, ecoute par
  // MapView/ProfileChart/DataTable), puis rouvre avec le champ vise rempli.
  const handlePickPk = (field: 'pkStart' | 'pkEnd') => {
    beginPkPick((pk) => setDraft((d) => (d ? { ...d, [field]: String(pk) } : d)))
  }

  const isGravitaire = regime !== 'refoulement'
  // Au minimum de quoi lancer un calcul plus tard (consigne utilisateur : le troncon passe "au
  // vert"/valide des qu'on enregistre) — le debit de tete (commun aux deux regimes), plus le
  // niveau amont en gravitaire ou la residuelle aval en refoulement.
  const hasMinimumData =
    hydraulics.headFlow != null &&
    (isGravitaire ? resolvedMax.value != null && resolvedMin.value != null : hydraulics.downstreamResidualPressure != null)

  return (
    <>
      <div hidden={pkPickResolver != null}>
      <Modal
        title={`Tronçon ${label}`}
        onClose={onClose}
        error={error}
        confirmLabel="Enregistrer"
        onConfirm={handleConfirm}
        confirmDisabled={submitting || !hasMinimumData}
        wide
      >
        <div className="modal-field-grid">
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
            <label htmlFor="troncon-min-pressure-exclusion">Zone d'exclusion (m)</label>
            <input
              id="troncon-min-pressure-exclusion"
              type="number"
              value={hydraulics.minPressureExclusionM ?? ''}
              onChange={(e) => setHydraulicField('minPressureExclusionM', e.target.value)}
            />
            <span className="modal-field-hint">
              Distance depuis l'ouvrage de départ où la pression min n'est pas opposable (alerte informative seulement).
            </span>
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
        </div>

        {phasingEnabled && (
          <div className="troncon-constraints-panel">
            <div className="troncon-constraints-header">
              <h3>Phasage</h3>
            </div>
            <div className="modal-field">
              <label htmlFor="troncon-phase">Phase de réalisation</label>
              <select id="troncon-phase" value={phaseId} onChange={(e) => setPhaseId(e.target.value)}>
                <option value="">— Non affecté —</option>
                {listPhaseOptions(project).map((p) => (
                  <option key={p.id} value={p.id}>Phase {p.index}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        <div className="troncon-constraints-panel">
          <div className="troncon-constraints-header">
            <h3>Contraintes</h3>
            <div className="troncon-constraints-actions">
              <button type="button" className="modal-btn modal-btn-cancel" onClick={handleAddConstraintClick} disabled={savingConstraints}>
                Ajouter
              </button>
              <button
                type="button"
                className="modal-btn modal-btn-cancel"
                onClick={handleClearAllConstraints}
                disabled={savingConstraints || constraints.every((c) => c.is_existing)}
              >
                Tout supprimer
              </button>
            </div>
          </div>
          <span className="modal-field-hint">
            Matériau/DN/classe imposés sur tout ou partie du tronçon (PK vide = depuis le début / jusqu'à la fin).
          </span>
          {constraintError && <div className="modal-error">{constraintError}</div>}
          {constraints.length > 0 && (
            <table className="troncon-constraints-table">
              <thead>
                <tr>
                  <th>Matériau</th>
                  <th>DN</th>
                  <th>Classe</th>
                  <th>PK début</th>
                  <th>PK fin</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {constraints.map((c) => (
                  <tr key={c.id} className={c.is_existing ? 'troncon-constraint-existing' : ''}>
                    <td>{c.material ?? '—'}</td>
                    <td>{c.dn ?? '—'}</td>
                    <td>{c.pressure_class ?? '—'}</td>
                    <td>{c.pk_start != null ? Math.round(c.pk_start) : 'début'}</td>
                    <td>{c.pk_end != null ? Math.round(c.pk_end) : 'fin'}</td>
                    <td>
                      {c.is_existing ? (
                        <span className="modal-field-hint">élément existant</span>
                      ) : (
                        <>
                          <button type="button" className="btn-row-icon" title="Modifier" onClick={() => handleEditConstraintClick(c)}>
                            ✎
                          </button>
                          <button
                            type="button"
                            className="btn-row-icon"
                            title="Supprimer"
                            onClick={() => handleDeleteConstraint(c.id)}
                            disabled={savingConstraints}
                          >
                            🗑
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {draft && (
            <div className="troncon-constraint-draft">
              <div className="modal-field">
                <label htmlFor="constraint-material">Matériau</label>
                <select
                  id="constraint-material"
                  value={draft.material}
                  onChange={(e) => setDraft((d) => (d ? { ...d, material: e.target.value } : d))}
                >
                  <option value="">— aucun —</option>
                  {activeMaterials.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
              <div className="modal-field">
                <label htmlFor="constraint-dn">DN</label>
                <select id="constraint-dn" value={draft.dn} onChange={(e) => setDraft((d) => (d ? { ...d, dn: e.target.value } : d))}>
                  <option value="">— aucun —</option>
                  {dnsForMaterial.map((dn) => (
                    <option key={dn} value={dn}>
                      {dn}
                    </option>
                  ))}
                </select>
              </div>
              <div className="modal-field">
                <label htmlFor="constraint-class">Classe</label>
                <select
                  id="constraint-class"
                  value={draft.pressureClass}
                  onChange={(e) => setDraft((d) => (d ? { ...d, pressureClass: e.target.value } : d))}
                >
                  <option value="">— aucune —</option>
                  {classesForSelection.map((pc) => (
                    <option key={pc} value={pc}>
                      {pc}
                    </option>
                  ))}
                </select>
              </div>
              <div className="modal-field">
                <label htmlFor="constraint-pk-start">PK début</label>
                <div className="troncon-constraint-pk-input">
                  <input
                    id="constraint-pk-start"
                    type="number"
                    placeholder="début du tronçon"
                    value={draft.pkStart}
                    onChange={(e) => setDraft((d) => (d ? { ...d, pkStart: e.target.value } : d))}
                  />
                  <button type="button" className="btn-row-icon" title="Choisir sur la carte/le profil" onClick={() => handlePickPk('pkStart')}>
                    …
                  </button>
                </div>
              </div>
              <div className="modal-field">
                <label htmlFor="constraint-pk-end">PK fin</label>
                <div className="troncon-constraint-pk-input">
                  <input
                    id="constraint-pk-end"
                    type="number"
                    placeholder="fin du tronçon"
                    value={draft.pkEnd}
                    onChange={(e) => setDraft((d) => (d ? { ...d, pkEnd: e.target.value } : d))}
                  />
                  <button type="button" className="btn-row-icon" title="Choisir sur la carte/le profil" onClick={() => handlePickPk('pkEnd')}>
                    …
                  </button>
                </div>
              </div>
              <div className="troncon-constraints-actions">
                <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setDraft(null)}>
                  Annuler
                </button>
                <button type="button" className="modal-btn modal-btn-confirm" onClick={handleSaveDraft} disabled={savingConstraints}>
                  {draft.id ? 'Modifier' : 'Ajouter'}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="troncon-constraints-panel">
          <div className="troncon-constraints-header">
            <h3>Éléments existants</h3>
            <div className="troncon-constraints-actions">
              <button type="button" className="modal-btn modal-btn-cancel" onClick={handleAddExistingClick} disabled={savingConstraints}>
                Ajouter
              </button>
            </div>
          </div>
          <span className="modal-field-hint">
            Conduites déjà en place — Matériau, DN et Classe obligatoires. Apparaissent grisées dans le tableau Contraintes.
          </span>
          {constraintError && <div className="modal-error">{constraintError}</div>}
          {existingElements.length > 0 && (
            <table className="troncon-constraints-table">
              <thead>
                <tr>
                  <th>Matériau</th>
                  <th>DN</th>
                  <th>Classe</th>
                  <th>PK début</th>
                  <th>PK fin</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {existingElements.map((c) => (
                  <tr key={c.id}>
                    <td>{c.material}</td>
                    <td>{c.dn}</td>
                    <td>{c.pressure_class}</td>
                    <td>{c.pk_start != null ? Math.round(c.pk_start) : 'début'}</td>
                    <td>{c.pk_end != null ? Math.round(c.pk_end) : 'fin'}</td>
                    <td>
                      <button type="button" className="btn-row-icon" title="Modifier" onClick={() => handleEditExistingClick(c)}>
                        ✎
                      </button>
                      <button
                        type="button"
                        className="btn-row-icon"
                        title="Supprimer"
                        onClick={() => handleDeleteExisting(c.id)}
                        disabled={savingConstraints}
                      >
                        🗑
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {existingDraft && (
            <div className="troncon-constraint-draft">
              <div className="modal-field">
                <label htmlFor="existing-material">Matériau *</label>
                <select
                  id="existing-material"
                  value={existingDraft.material}
                  onChange={(e) => setExistingDraft((d) => (d ? { ...d, material: e.target.value } : d))}
                >
                  <option value="">— choisir —</option>
                  {activeMaterials.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
              <div className="modal-field">
                <label htmlFor="existing-dn">DN *</label>
                <select
                  id="existing-dn"
                  value={existingDraft.dn}
                  onChange={(e) => setExistingDraft((d) => (d ? { ...d, dn: e.target.value } : d))}
                >
                  <option value="">— choisir —</option>
                  {dnsForExistingMaterial.map((dn) => (
                    <option key={dn} value={dn}>
                      {dn}
                    </option>
                  ))}
                </select>
              </div>
              <div className="modal-field">
                <label htmlFor="existing-class">Classe *</label>
                <select
                  id="existing-class"
                  value={existingDraft.pressureClass}
                  onChange={(e) => setExistingDraft((d) => (d ? { ...d, pressureClass: e.target.value } : d))}
                >
                  <option value="">— choisir —</option>
                  {classesForExistingSelection.map((pc) => (
                    <option key={pc} value={pc}>
                      {pc}
                    </option>
                  ))}
                </select>
              </div>
              <div className="modal-field">
                <label htmlFor="existing-pk-start">PK début</label>
                <div className="troncon-constraint-pk-input">
                  <input
                    id="existing-pk-start"
                    type="number"
                    placeholder="début du tronçon"
                    value={existingDraft.pkStart}
                    onChange={(e) => setExistingDraft((d) => (d ? { ...d, pkStart: e.target.value } : d))}
                  />
                  <button type="button" className="btn-row-icon" title="Choisir sur la carte/le profil" onClick={() => handlePickExistingPk('pkStart')}>
                    …
                  </button>
                </div>
              </div>
              <div className="modal-field">
                <label htmlFor="existing-pk-end">PK fin</label>
                <div className="troncon-constraint-pk-input">
                  <input
                    id="existing-pk-end"
                    type="number"
                    placeholder="fin du tronçon"
                    value={existingDraft.pkEnd}
                    onChange={(e) => setExistingDraft((d) => (d ? { ...d, pkEnd: e.target.value } : d))}
                  />
                  <button type="button" className="btn-row-icon" title="Choisir sur la carte/le profil" onClick={() => handlePickExistingPk('pkEnd')}>
                    …
                  </button>
                </div>
              </div>
              <div className="troncon-constraints-actions">
                <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setExistingDraft(null)}>
                  Annuler
                </button>
                <button type="button" className="modal-btn modal-btn-confirm" onClick={handleSaveExistingDraft} disabled={savingConstraints}>
                  {existingDraft.id ? 'Modifier' : 'Ajouter'}
                </button>
              </div>
            </div>
          )}
        </div>
      </Modal>
      </div>
      {pkPickResolver && (
        <div className="pk-pick-banner">
          <span>Cliquez sur la carte, le profil graphique ou le profil Data pour choisir le PK…</span>
          <button type="button" className="modal-btn modal-btn-cancel" onClick={cancelPkPick}>
            Annuler
          </button>
        </div>
      )}
    </>
  )
}
