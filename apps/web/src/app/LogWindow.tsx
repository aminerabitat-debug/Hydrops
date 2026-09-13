// Fenetre log (consigne utilisateur : "les messages d'erreur doivent se répartir entre la barre
// d'état et le log, avec plus de détails dans le log") — panneau DOCKE juste au-dessus de la barre
// d'etat (pas une modale : pas de fond assombri, l'utilisateur continue d'interagir avec le reste
// de l'appli pendant qu'elle est ouverte), affichable/masquable a la demande via le bouton dedie de
// la barre d'etat (cf. App.tsx). Alimentee par setStatusMessage (state/store.ts) pour les types
// 'warning'/'error' uniquement.

import { useAppStore } from '../state/store'

const LOG_ICONS: Record<string, string> = { warning: '⚠️', error: '✕', info: 'ℹ️', success: '✅' }

export function LogWindow() {
  const logEntries = useAppStore((s) => s.logEntries)
  const clearLog = useAppStore((s) => s.clearLog)
  const toggleLogWindow = useAppStore((s) => s.toggleLogWindow)

  return (
    <div className="log-window">
      <div className="log-window-header">
        <h3>Journal des messages</h3>
        <div className="log-window-actions">
          <button type="button" className="modal-btn modal-btn-cancel" onClick={clearLog} disabled={logEntries.length === 0}>
            Vider
          </button>
          <button type="button" className="btn-row-icon" title="Fermer le journal" aria-label="Fermer le journal" onClick={toggleLogWindow}>
            ✕
          </button>
        </div>
      </div>
      <div className="log-window-body">
        {logEntries.length === 0 ? (
          <p className="empty-hint">Aucun message d'avertissement ou d'erreur pour l'instant.</p>
        ) : (
          [...logEntries]
            .reverse()
            .map((entry) => (
              <div key={entry.id} className={`log-entry log-entry--${entry.type}`}>
                <span className="log-entry-icon" aria-hidden="true">{LOG_ICONS[entry.type] ?? 'ℹ️'}</span>
                <span className="log-entry-time">
                  {new Date(entry.timestamp).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
                <span className="log-entry-text">{entry.detail}</span>
              </div>
            ))
        )}
      </div>
    </div>
  )
}
