// Fenêtre "Conduites" (menu Base de données, consigne utilisateur) : jeu préliminaire de test
// fourni par l'utilisateur, à mettre à jour plus tard. La case "Actif" exclut une ligne des
// recherches du moteur de calcul sans la supprimer — certains DN ne sont pas toujours standards
// selon les cas (consigne utilisateur). Les cases cochées/décochées restent LOCALES tant que
// "Enregistrer" n'a pas été cliqué (consigne utilisateur) — "Réinitialiser" revient à la config
// telle qu'enregistrée sur le serveur, sans fermer la fenêtre.

import { useEffect, useState } from 'react'

import { Modal } from './Modal'
import { api } from '../shared/apiClient'
import type { PipeCatalogRow } from '../shared/types'

interface ConduitesWindowProps {
  onClose: () => void
}

function formatMoney(value: number): string {
  return value.toLocaleString('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

export function ConduitesWindow({ onClose }: ConduitesWindowProps) {
  const [savedRows, setSavedRows] = useState<PipeCatalogRow[]>([])
  const [rows, setRows] = useState<PipeCatalogRow[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .listConduites()
      .then((r) => {
        setSavedRows(r)
        setRows(r)
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false))
  }, [])

  const toggleActive = (rowId: number) => {
    setRows((rs) => rs.map((r) => (r.id === rowId ? { ...r, active: !r.active } : r)))
  }

  const hasUnsavedChanges = rows.some((r, i) => r.active !== savedRows[i]?.active)

  const handleReset = () => setRows(savedRows)

  const handleSave = async () => {
    setSubmitting(true)
    setError('')
    try {
      const changed = rows.filter((r, i) => r.active !== savedRows[i]?.active)
      await Promise.all(changed.map((r) => api.patchConduite(r.id, r.active)))
      setSavedRows(rows)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="Conduites"
      onClose={onClose}
      error={error}
      confirmLabel="Enregistrer"
      onConfirm={handleSave}
      confirmDisabled={submitting || !hasUnsavedChanges}
      secondaryLabel="Réinitialiser"
      onSecondary={handleReset}
      secondaryDisabled={submitting || !hasUnsavedChanges}
      wide
    >
      <p style={{ margin: 0, color: 'var(--muted)', fontSize: 12 }}>
        Base préliminaire pour les tests, à mettre à jour plus tard. Décocher "Actif" exclut une ligne des
        recherches du calcul sans la supprimer (DN non standard selon les cas). Les cases restent locales
        tant que "Enregistrer" n'a pas été cliqué.
      </p>
      {loading ? (
        <p className="empty-hint">Chargement…</p>
      ) : (
        <div className="data-window-table-wrap">
          <table className="data-window-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>DN</th>
                <th>DI</th>
                <th>Matériau</th>
                <th>Classe</th>
                <th>PMS</th>
                <th>Prix FTP</th>
                <th>Prix Fourniture</th>
                <th>Prix APS (Dhs)</th>
                <th>Actif</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className={row.active ? '' : 'row-inactive'}>
                  <td>{row.id}</td>
                  <td>{row.dn}</td>
                  <td>{row.di}</td>
                  <td>{row.material}</td>
                  <td>{row.pressure_class}</td>
                  <td>{row.pms}</td>
                  <td>{formatMoney(row.prix_ftp)}</td>
                  <td>{formatMoney(row.prix_fourniture)}</td>
                  <td>{formatMoney(row.prix_aps)}</td>
                  <td>
                    <input type="checkbox" checked={row.active} onChange={() => toggleActive(row.id)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
