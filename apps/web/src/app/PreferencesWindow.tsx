// Fenêtre "Préférences" (menu Calcul, consigne utilisateur) : rugosité par matériau (valeurs par
// défaut modifiables), critères de choix des matériaux des conduites (reconstitution du tableau
// fourni — plage de DN x fluide -> matériaux autorisés, éditable : un point de départ, pas une
// vérité figée, cf. cdc §15), rappel de la loi de calcul des pertes de charge (grisé pour le
// moment), température du fluide et majoration pertes de charge singulières.

import { useEffect, useState } from 'react'

import { Modal } from './Modal'
import { api } from '../shared/apiClient'
import { FLUIDE_OPTIONS } from '../shared/ouvrageFields'
import type { CalculationPreferences, CatalogMaterial, MaterialCriterionRule } from '../shared/types'

interface PreferencesWindowProps {
  sessionId: string
  onClose: () => void
  onSaved: () => void
}

const ALL_MATERIALS_FALLBACK = ['PVC', 'PEHD', 'BP', 'FD', 'FD JV', 'Acier', 'PRV']

function emptyRule(): MaterialCriterionRule {
  return { dn_min: null, dn_max: null, fluid: null, materials: [] }
}

export function PreferencesWindow({ sessionId, onClose, onSaved }: PreferencesWindowProps) {
  const [materials, setMaterials] = useState<CatalogMaterial[]>([])
  const [prefs, setPrefs] = useState<CalculationPreferences | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    Promise.all([api.listCatalogMaterials(), api.getPreferences(sessionId)])
      .then(([m, p]) => {
        setMaterials(m)
        setPrefs(p)
      })
      .catch((e) => setError((e as Error).message))
  }, [sessionId])

  const materialCodes = materials.length > 0 ? materials.map((m) => m.material) : ALL_MATERIALS_FALLBACK

  const setRoughness = (material: string, value: string) => {
    setPrefs((p) => (p ? { ...p, roughness_by_material: { ...p.roughness_by_material, [material]: Number(value) || 0 } } : p))
  }

  const updateRule = (index: number, patch: Partial<MaterialCriterionRule>) => {
    setPrefs((p) =>
      p ? { ...p, material_criteria: p.material_criteria.map((r, i) => (i === index ? { ...r, ...patch } : r)) } : p,
    )
  }

  const toggleRuleMaterial = (index: number, material: string) => {
    setPrefs((p) => {
      if (!p) return p
      const rule = p.material_criteria[index]
      const next = rule.materials.includes(material)
        ? rule.materials.filter((m) => m !== material)
        : [...rule.materials, material]
      return { ...p, material_criteria: p.material_criteria.map((r, i) => (i === index ? { ...r, materials: next } : r)) }
    })
  }

  const addRule = () => setPrefs((p) => (p ? { ...p, material_criteria: [...p.material_criteria, emptyRule()] } : p))
  const removeRule = (index: number) =>
    setPrefs((p) => (p ? { ...p, material_criteria: p.material_criteria.filter((_, i) => i !== index) } : p))

  const handleConfirm = async () => {
    if (!prefs) return
    setSubmitting(true)
    setError('')
    try {
      await api.putPreferences(sessionId, prefs)
      onSaved()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  if (!prefs) {
    return (
      <Modal title="Préférences" onClose={onClose} error={error} confirmLabel="Fermer" onConfirm={onClose} wide>
        <p className="empty-hint">Chargement…</p>
      </Modal>
    )
  }

  return (
    <Modal
      title="Préférences de calcul"
      onClose={onClose}
      error={error}
      confirmLabel="Enregistrer"
      onConfirm={handleConfirm}
      confirmDisabled={submitting}
      wide
    >
      <div className="preferences-section">
        <div className="preferences-section-title">Rugosité par matériau (mm)</div>
        <div className="preferences-roughness-grid">
          {materialCodes.map((material) => (
            <div className="preferences-roughness-item" key={material}>
              <label htmlFor={`roughness-${material}`}>{material}</label>
              <input
                id={`roughness-${material}`}
                type="number"
                step="0.001"
                value={prefs.roughness_by_material[material] ?? ''}
                onChange={(e) => setRoughness(material, e.target.value)}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="preferences-section">
        <div className="preferences-section-title">Critères de choix des matériaux des conduites</div>
        <p style={{ margin: 0, color: 'var(--muted)', fontSize: 12 }}>
          Plage de DN (mm) et, éventuellement, un fluide précis ("Tous" = s'applique à tous les fluides) →
          matériaux autorisés. Point de départ éditable, à corriger selon vos règles.
        </p>
        {prefs.material_criteria.map((rule, i) => (
          <div className="criteria-row" key={i}>
            <div className="modal-field">
              <label>DN min</label>
              <input
                type="number"
                value={rule.dn_min ?? ''}
                onChange={(e) => updateRule(i, { dn_min: e.target.value === '' ? null : Number(e.target.value) })}
              />
            </div>
            <div className="modal-field">
              <label>DN max</label>
              <input
                type="number"
                value={rule.dn_max ?? ''}
                onChange={(e) => updateRule(i, { dn_max: e.target.value === '' ? null : Number(e.target.value) })}
              />
            </div>
            <div className="modal-field">
              <label>Fluide</label>
              <select
                value={rule.fluid ?? ''}
                onChange={(e) => updateRule(i, { fluid: e.target.value === '' ? null : e.target.value })}
              >
                <option value="">Tous les fluides</option>
                {FLUIDE_OPTIONS.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
              <div className="criteria-row-materials">
                {materialCodes.map((material) => (
                  <label key={material} className="modal-checkbox-label" style={{ fontSize: 12 }}>
                    <input
                      type="checkbox"
                      checked={rule.materials.includes(material)}
                      onChange={() => toggleRuleMaterial(i, material)}
                    />
                    <span>{material}</span>
                  </label>
                ))}
              </div>
            </div>
            <button type="button" className="btn-small" onClick={() => removeRule(i)}>✕</button>
          </div>
        ))}
        <button type="button" className="btn-small" onClick={addRule} style={{ alignSelf: 'flex-start' }}>
          + Ajouter une règle
        </button>
      </div>

      <div className="preferences-section">
        <div className="preferences-section-title">Hypothèses de calcul des pertes de charge</div>
        <div className="formula-reminder">
          Darcy-Weisbach : <code>J = f · V² / (2 · g · D)</code> — perte de charge linéaire unitaire (m/m).
          <br />
          Colebrook-White : <code>1/√f = −2·log₁₀( k/(3,7·D) + 2,51/(Re·√f) )</code> — résolution itérative
          du facteur de frottement f (régime laminaire, Re&lt;2300 : f = 64/Re).
        </div>
        <div className="modal-field">
          <label htmlFor="pref-temperature">Température du fluide (°C)</label>
          <input
            id="pref-temperature"
            type="number"
            value={prefs.fluid_temperature_c}
            onChange={(e) => setPrefs((p) => (p ? { ...p, fluid_temperature_c: Number(e.target.value) || 0 } : p))}
          />
        </div>
        <div className="modal-field">
          <label htmlFor="pref-markup">Majoration pour pertes de charge singulières (%)</label>
          <input
            id="pref-markup"
            type="number"
            value={prefs.singular_loss_markup_pct}
            onChange={(e) => setPrefs((p) => (p ? { ...p, singular_loss_markup_pct: Number(e.target.value) || 0 } : p))}
          />
        </div>
      </div>

      <div className="preferences-section">
        <div className="preferences-section-title">Valeurs par défaut des tronçons</div>
        <p style={{ margin: 0, color: 'var(--muted)', fontSize: 12 }}>
          Proposées à l'ouverture de "Modifier le tronçon" tant qu'il n'a pas déjà sa propre valeur — laisser vide
          pour ne rien préremplir.
        </p>
        <div className="modal-field">
          <label htmlFor="pref-min-pressure">Pression min (m)</label>
          <input
            id="pref-min-pressure"
            type="number"
            value={prefs.default_min_pressure ?? ''}
            onChange={(e) =>
              setPrefs((p) => (p ? { ...p, default_min_pressure: e.target.value === '' ? null : Number(e.target.value) } : p))
            }
          />
        </div>
        <div className="modal-field">
          <label htmlFor="pref-residual-pressure">Pression résiduelle aval (m)</label>
          <input
            id="pref-residual-pressure"
            type="number"
            value={prefs.default_downstream_residual_pressure ?? ''}
            onChange={(e) =>
              setPrefs((p) =>
                p ? { ...p, default_downstream_residual_pressure: e.target.value === '' ? null : Number(e.target.value) } : p,
              )
            }
          />
        </div>
        <div className="modal-field">
          <label htmlFor="pref-max-velocity">Vitesse Max (m/s)</label>
          <input
            id="pref-max-velocity"
            type="number"
            value={prefs.default_max_velocity ?? ''}
            onChange={(e) =>
              setPrefs((p) => (p ? { ...p, default_max_velocity: e.target.value === '' ? null : Number(e.target.value) } : p))
            }
          />
        </div>
        <div className="modal-field">
          <label htmlFor="pref-min-velocity">Vitesse Min (m/s)</label>
          <input
            id="pref-min-velocity"
            type="number"
            value={prefs.default_min_velocity ?? ''}
            onChange={(e) =>
              setPrefs((p) => (p ? { ...p, default_min_velocity: e.target.value === '' ? null : Number(e.target.value) } : p))
            }
          />
        </div>
      </div>
    </Modal>
  )
}
