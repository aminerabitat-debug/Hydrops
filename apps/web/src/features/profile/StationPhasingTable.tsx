// Tableau Génie Civil / Équipement (lignes) x Phases (colonnes) pour les stations (pumping_station,
// treatment_plant — consigne utilisateur). Chaque cellule : case "existant" OU débit (m3/h) pour
// l'investissement de cette phase, ou vide (aucun investissement prevu). Stocke dans
// Node.data.station_phasing, cf. shared/ouvrageFields.ts.

import { STATION_PHASING_ROWS, type StationPhaseCell, type StationPhasingData } from '../../shared/ouvrageFields'
import type { PhaseOption } from '../../shared/phasing'

interface StationPhasingTableProps {
  phasing: StationPhasingData
  phases: PhaseOption[]
  onChange: (phasing: StationPhasingData) => void
}

export function StationPhasingTable({ phasing, phases, onChange }: StationPhasingTableProps) {
  const setCell = (row: 'civil' | 'equipment', phaseId: string, cell: StationPhaseCell) => {
    onChange({ ...phasing, [row]: { ...phasing[row], [phaseId]: cell } })
  }

  return (
    <div className="modal-field">
      <label>Phasage de la station</label>
      <div className="troncon-constraints-table-wrap">
        <table className="troncon-constraints-table station-phasing-table">
          <thead>
            <tr>
              <th></th>
              {phases.map((p) => (
                <th key={p.id}>Phase {p.index}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {STATION_PHASING_ROWS.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                {phases.map((p) => {
                  const cell = phasing[row.key][p.id] ?? { existing: false }
                  return (
                    <td key={p.id}>
                      <div className="station-phasing-cell">
                        <label className="modal-checkbox-label">
                          <input
                            type="checkbox"
                            checked={cell.existing}
                            onChange={(e) =>
                              setCell(row.key, p.id, { existing: e.target.checked, flow_m3h: cell.flow_m3h })
                            }
                          />
                          <span>Existant</span>
                        </label>
                        <input
                          type="number"
                          placeholder="Débit m³/h"
                          disabled={cell.existing}
                          value={cell.flow_m3h ?? ''}
                          onChange={(e) =>
                            setCell(row.key, p.id, {
                              existing: cell.existing,
                              flow_m3h: e.target.value === '' ? undefined : Number(e.target.value),
                            })
                          }
                        />
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="modal-field-hint">
        Pour chaque cellule : cocher "Existant" si déjà en place, ou renseigner le débit (m³/h) investi
        à cette phase. Laisser vide si aucun investissement n'est prévu à cette phase.
      </p>
    </div>
  )
}
