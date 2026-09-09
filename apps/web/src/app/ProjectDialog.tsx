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
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

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
    </Modal>
  )
}
