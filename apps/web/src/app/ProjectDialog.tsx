// Creation ET edition de projet (cdc §5.1) — meme formulaire dans les deux cas ("Paramètres du
// projet" depuis l'arborescence rouvre ce dialogue pre-rempli). Informations communes a toutes
// les variantes : volume annuel a livrer, annee du 1er investissement, annee de mise en service,
// duree d'amortissement, et une evolution optionnelle du volume (colle depuis Excel, cases vides
// interpolees/extrapolees — cf. shared/volumeSeries.ts).

import { useMemo, useState } from 'react'

import { Modal } from './Modal'
import type { ProjectFormPayload } from '../shared/apiClient'
import type { Project } from '../shared/types'
import { buildVolumeSeries } from '../shared/volumeSeries'

interface ProjectDialogProps {
  mode: 'create' | 'edit'
  initialProject?: Project
  onClose: () => void
  onSubmit: (payload: ProjectFormPayload) => Promise<void>
}

const CURRENT_YEAR = new Date().getFullYear()

export function ProjectDialog({ mode, initialProject, onClose, onSubmit }: ProjectDialogProps) {
  const [name, setName] = useState(initialProject?.name ?? 'Nouveau projet')
  const [firstInvestmentYear, setFirstInvestmentYear] = useState(
    String(initialProject?.first_investment_year ?? CURRENT_YEAR),
  )
  const [commissioningYear, setCommissioningYear] = useState(
    String(initialProject?.commissioning_year ?? CURRENT_YEAR + 2),
  )
  const [amortizationYears, setAmortizationYears] = useState(String(initialProject?.amortization_years ?? 25))
  const [hasVariableVolume, setHasVariableVolume] = useState(initialProject?.annual_volume.mode === 'table')
  const [constantVolume, setConstantVolume] = useState(
    String(initialProject?.annual_volume.mode === 'constant' ? initialProject.annual_volume.value : 10),
  )
  const [pastedVolumes, setPastedVolumes] = useState(() =>
    initialProject?.annual_volume.mode === 'table'
      ? initialProject.annual_volume.points.map((p) => String(p.value)).join('\n')
      : '',
  )
  // Phasage (consigne utilisateur : case a cocher sous "Volume annuel a livrer", decochee par
  // defaut) — la phase 1 est implicite (annee du 1er investissement/mise en service ci-dessus),
  // ce tableau ne porte que les phases 2+ ajoutees par l'utilisateur. Les erreurs de coherence
  // (ordre chronologique, fenetre d'amortissement) sont validees cote serveur et affichees via le
  // meme bandeau d'erreur que le reste du formulaire (pas de duplication de la logique ici).
  const [phasingEnabled, setPhasingEnabled] = useState(initialProject?.phasing_enabled ?? false)
  const [phases, setPhases] = useState(() =>
    (initialProject?.phases ?? []).map((p) => ({
      id: p.id,
      index: p.index,
      investmentYear: String(p.investment_year),
      commissioningYear: String(p.commissioning_year),
    })),
  )
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleAddPhase = () => {
    const nextIndex = phases.length > 0 ? Math.max(...phases.map((p) => p.index)) + 1 : 2
    setPhases((prev) => [
      ...prev,
      { id: crypto.randomUUID(), index: nextIndex, investmentYear: '', commissioningYear: '' },
    ])
  }
  const handleRemovePhase = (id: string) => setPhases((prev) => prev.filter((p) => p.id !== id))
  const handlePhaseFieldChange = (id: string, field: 'investmentYear' | 'commissioningYear', value: string) =>
    setPhases((prev) => prev.map((p) => (p.id === id ? { ...p, [field]: value } : p)))

  const amortizationCount = Math.max(1, Number(amortizationYears) || 1)
  const volumeSeries = useMemo(
    () => buildVolumeSeries(pastedVolumes, Number(commissioningYear) || CURRENT_YEAR, amortizationCount),
    [pastedVolumes, commissioningYear, amortizationCount],
  )

  const handleConfirm = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError("L'intitulé du projet est obligatoire.")
      return
    }
    setSubmitting(true)
    setError('')
    try {
      await onSubmit({
        name: trimmed,
        first_investment_year: Number(firstInvestmentYear),
        commissioning_year: Number(commissioningYear),
        amortization_years: amortizationCount,
        ...(hasVariableVolume
          ? { annual_volume_points: volumeSeries.map((v) => ({ year: v.year, value: v.value })) }
          : { annual_volume_value: Number(constantVolume) }),
        phasing_enabled: phasingEnabled,
        phases: phasingEnabled
          ? phases.map((p) => ({
              id: p.id,
              index: p.index,
              investment_year: Number(p.investmentYear),
              commissioning_year: Number(p.commissioningYear),
            }))
          : [],
      })
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={mode === 'create' ? 'Nouveau projet' : 'Paramètres du projet'}
      onClose={onClose}
      error={error}
      confirmLabel={mode === 'create' ? 'Créer' : 'Enregistrer'}
      onConfirm={handleConfirm}
      confirmDisabled={!name.trim() || submitting}
    >
      <div className="modal-field">
        <label htmlFor="project-name">Nom du projet</label>
        <input id="project-name" type="text" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="modal-field">
        <label htmlFor="project-first-investment">Année du 1er investissement</label>
        <input
          id="project-first-investment"
          type="number"
          value={firstInvestmentYear}
          onChange={(e) => setFirstInvestmentYear(e.target.value)}
        />
      </div>
      <div className="modal-field">
        <label htmlFor="project-commissioning">Année de mise en service</label>
        <input
          id="project-commissioning"
          type="number"
          value={commissioningYear}
          onChange={(e) => setCommissioningYear(e.target.value)}
        />
      </div>
      <div className="modal-field">
        <label htmlFor="project-amortization">Durée d'amortissement (années)</label>
        <input
          id="project-amortization"
          type="number"
          min="1"
          value={amortizationYears}
          onChange={(e) => setAmortizationYears(e.target.value)}
        />
      </div>

      <div className="modal-field">
        <label className="modal-checkbox-label">
          <input
            type="checkbox"
            checked={hasVariableVolume}
            onChange={(e) => setHasVariableVolume(e.target.checked)}
          />
          <span>Volume annuel variable</span>
        </label>
      </div>

      {!hasVariableVolume ? (
        <div className="modal-field">
          <label htmlFor="project-volume">Volume annuel à livrer (Mm³/an)</label>
          <input
            id="project-volume"
            type="number"
            min="0"
            step="0.1"
            value={constantVolume}
            onChange={(e) => setConstantVolume(e.target.value)}
          />
        </div>
      ) : (
        <>
          <div className="modal-field">
            <label htmlFor="project-volume-paste">
              {`Volumes annuels (Mm³/an) — coller depuis Excel, une valeur par ligne à partir de l'année de mise en service (${amortizationCount} valeur${amortizationCount > 1 ? 's' : ''} attendue${amortizationCount > 1 ? 's' : ''}, cases vides interpolées)`}
            </label>
            <textarea
              id="project-volume-paste"
              value={pastedVolumes}
              onChange={(e) => setPastedVolumes(e.target.value)}
              rows={4}
              placeholder={'10\n\n15\n...'}
            />
          </div>
          <div className="volume-preview">
            <table className="volume-preview-table">
              <thead>
                <tr>
                  <th>Année</th>
                  <th>Volume (Mm³/an)</th>
                </tr>
              </thead>
              <tbody>
                {volumeSeries.map((v) => (
                  <tr key={v.year} className={v.wasPasted ? '' : 'interpolated'}>
                    <td>{v.year}</td>
                    <td>
                      {v.value.toFixed(2)}
                      {!v.wasPasted && ' *'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="volume-preview-hint">* valeur interpolée/extrapolée (case vide)</p>
          </div>
        </>
      )}

      <div className="modal-field">
        <label className="modal-checkbox-label">
          <input type="checkbox" checked={phasingEnabled} onChange={(e) => setPhasingEnabled(e.target.checked)} />
          <span>Phasage</span>
        </label>
        <span className="modal-field-hint">
          L'année du 1er investissement ci-dessus est la Phase 1. Ajoutez les phases suivantes ci-dessous.
        </span>
      </div>

      {phasingEnabled && (
        <div className="project-phases-panel">
          <table className="troncon-constraints-table">
            <thead>
              <tr>
                <th>Phase</th>
                <th>Année d'investissement</th>
                <th>Année de mise en service</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>1</td>
                <td>{firstInvestmentYear}</td>
                <td>{commissioningYear}</td>
                <td></td>
              </tr>
              {phases.map((p) => (
                <tr key={p.id}>
                  <td>{p.index}</td>
                  <td>
                    <input
                      type="number"
                      value={p.investmentYear}
                      onChange={(e) => handlePhaseFieldChange(p.id, 'investmentYear', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      value={p.commissioningYear}
                      onChange={(e) => handlePhaseFieldChange(p.id, 'commissioningYear', e.target.value)}
                    />
                  </td>
                  <td>
                    <button type="button" className="btn-row-icon" title="Supprimer cette phase" onClick={() => handleRemovePhase(p.id)}>
                      🗑
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="modal-btn modal-btn-cancel" onClick={handleAddPhase}>
            Ajouter une phase
          </button>
        </div>
      )}
    </Modal>
  )
}
