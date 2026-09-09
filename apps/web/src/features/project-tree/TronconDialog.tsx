// Dialogue de modification des donnees d'un troncon (cdc §7/§8, consigne utilisateur) : Matériau/
// DN/Classe (catalogue conduite) + parametres hydrauliques dont le sous-ensemble affiche depend du
// regime (gravitaire vs refoulement, cf. shared/troncons.ts:tronconRegime — indetermine se voit
// proposer le meme jeu que gravitaire, un troncon pas encore rattache a une station de pompage
// n'ayant aucune raison de se limiter au sous-ensemble refoulement). Un troncon peut regrouper
// plusieurs segments (jonctions/piquages transparents en son sein) — modifier "le troncon" applique
// donc la MEME valeur a tous ses segments (cf. ProjectTree:handleSaveTroncon, un PATCH par segment_id).

import { useEffect, useMemo, useState } from 'react'

import { api } from '../../shared/apiClient'
import { Modal } from '../../app/Modal'
import type { TronconRegime } from '../../shared/troncons'
import type { CatalogDiameter, CatalogMaterial } from '../../shared/types'

export interface TronconHydraulicValues {
  upstreamWaterLevelMax?: number
  upstreamWaterLevelMin?: number
  minPressure?: number
  downstreamResidualPressure?: number
  maxVelocity?: number
}

interface TronconDialogProps {
  label: string
  regime: TronconRegime
  initialMaterial: string
  initialPressureClass: string
  initialDn: number
  initialHydraulics: TronconHydraulicValues
  onClose: () => void
  onSubmit: (material: string, dn: number, pressureClass: string, hydraulics: TronconHydraulicValues) => Promise<void>
}

export function TronconDialog({
  label,
  regime,
  initialMaterial,
  initialPressureClass,
  initialDn,
  initialHydraulics,
  onClose,
  onSubmit,
}: TronconDialogProps) {
  const [materials, setMaterials] = useState<CatalogMaterial[]>([])
  const [material, setMaterial] = useState(initialMaterial)
  const [pressureClass, setPressureClass] = useState(initialPressureClass)
  const [dn, setDn] = useState(initialDn)
  const [diameters, setDiameters] = useState<CatalogDiameter[]>([])
  const [hydraulics, setHydraulics] = useState<TronconHydraulicValues>(initialHydraulics)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api.listCatalogMaterials().then(setMaterials).catch(() => setMaterials([]))
  }, [])

  const pressureClasses = useMemo(
    () => materials.find((m) => m.material === material)?.pressure_classes ?? [],
    [materials, material],
  )

  useEffect(() => {
    if (!material || !pressureClass) return
    api
      .listCatalogDiameters(material, pressureClass)
      .then((fetched) => {
        setDiameters(fetched)
        // Le DN courant peut ne plus exister pour la nouvelle combinaison materiau/classe (ex.
        // DN160 n'existe pas en fonte ductile K9) — retomber sur le premier DN disponible plutot
        // que de soumettre un DN invalide (422 catalogue).
        setDn((current) => (fetched.some((d) => d.dn === current) ? current : (fetched[0]?.dn ?? current)))
      })
      .catch(() => setDiameters([]))
  }, [material, pressureClass])

  const handleMaterialChange = (newMaterial: string) => {
    setMaterial(newMaterial)
    const classes = materials.find((m) => m.material === newMaterial)?.pressure_classes ?? []
    if (classes.length > 0 && !classes.includes(pressureClass)) setPressureClass(classes[0])
  }

  const setHydraulicField = (key: keyof TronconHydraulicValues, value: string) => {
    setHydraulics((h) => ({ ...h, [key]: value === '' ? undefined : Number(value) }))
  }

  const handleConfirm = async () => {
    setSubmitting(true)
    setError('')
    try {
      await onSubmit(material, dn, pressureClass, hydraulics)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const isGravitaire = regime !== 'refoulement'

  return (
    <Modal
      title={`Modifier le tronçon ${label}`}
      onClose={onClose}
      error={error}
      confirmLabel="Enregistrer"
      onConfirm={handleConfirm}
      confirmDisabled={submitting || !material || !pressureClass || !dn}
    >
      <div className="modal-field">
        <label htmlFor="troncon-material">Matériau</label>
        <select id="troncon-material" value={material} onChange={(e) => handleMaterialChange(e.target.value)}>
          {materials.map((m) => (
            <option key={m.material} value={m.material}>{m.label}</option>
          ))}
        </select>
      </div>
      <div className="modal-field">
        <label htmlFor="troncon-class">Classe de pression</label>
        <select id="troncon-class" value={pressureClass} onChange={(e) => setPressureClass(e.target.value)}>
          {pressureClasses.map((c) => (
            <option key={c} value={c}>{c.toUpperCase()}</option>
          ))}
        </select>
      </div>
      <div className="modal-field">
        <label htmlFor="troncon-dn">DN</label>
        <select id="troncon-dn" value={dn} onChange={(e) => setDn(Number(e.target.value))}>
          {diameters.map((d) => (
            <option key={d.dn} value={d.dn}>{`DN${d.dn} (DI ${d.di.toFixed(1)} mm)`}</option>
          ))}
        </select>
      </div>

      {isGravitaire && (
        <>
          <div className="modal-field">
            <label htmlFor="troncon-upstream-max">Niveau du plan d'eau amont max (m)</label>
            <input
              id="troncon-upstream-max"
              type="number"
              value={hydraulics.upstreamWaterLevelMax ?? ''}
              onChange={(e) => setHydraulicField('upstreamWaterLevelMax', e.target.value)}
            />
          </div>
          <div className="modal-field">
            <label htmlFor="troncon-upstream-min">Niveau du plan d'eau amont min (m)</label>
            <input
              id="troncon-upstream-min"
              type="number"
              value={hydraulics.upstreamWaterLevelMin ?? ''}
              onChange={(e) => setHydraulicField('upstreamWaterLevelMin', e.target.value)}
            />
          </div>
          <div className="modal-field">
            <label htmlFor="troncon-min-pressure">Pression min (m)</label>
            <input
              id="troncon-min-pressure"
              type="number"
              value={hydraulics.minPressure ?? ''}
              onChange={(e) => setHydraulicField('minPressure', e.target.value)}
            />
          </div>
        </>
      )}
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
    </Modal>
  )
}
