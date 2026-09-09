// Dialogue de modification des donnees conduite (Matériau/DN/Classe) d'un troncon (cdc §7/§8,
// consigne utilisateur : "prévoir des boutons de suppression et de modification des... tronçons").
// Un troncon peut regrouper plusieurs segments (jonctions/piquages transparents en son sein) —
// modifier "le troncon" applique donc la MEME valeur a tous ses segments (cf.
// ProjectTree:handleSaveTroncon, un PATCH par segment_id).

import { useEffect, useMemo, useState } from 'react'

import { api } from '../../shared/apiClient'
import { Modal } from '../../app/Modal'
import type { CatalogDiameter, CatalogMaterial } from '../../shared/types'

interface TronconDialogProps {
  label: string
  initialMaterial: string
  initialPressureClass: string
  initialDn: number
  onClose: () => void
  onSubmit: (material: string, dn: number, pressureClass: string) => Promise<void>
}

export function TronconDialog({
  label,
  initialMaterial,
  initialPressureClass,
  initialDn,
  onClose,
  onSubmit,
}: TronconDialogProps) {
  const [materials, setMaterials] = useState<CatalogMaterial[]>([])
  const [material, setMaterial] = useState(initialMaterial)
  const [pressureClass, setPressureClass] = useState(initialPressureClass)
  const [dn, setDn] = useState(initialDn)
  const [diameters, setDiameters] = useState<CatalogDiameter[]>([])
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

  const handleConfirm = async () => {
    setSubmitting(true)
    setError('')
    try {
      await onSubmit(material, dn, pressureClass)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

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
    </Modal>
  )
}
