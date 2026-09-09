// Barre d'acces rapide (cdc §4) : raccourcis icones vers les actions Fichier les plus frequentes.

interface QuickBarProps {
  projectOpen: boolean
  onNewProject: () => void
  onOpenProject: () => void
  onSaveProject: () => void
}

export function QuickBar({ projectOpen, onNewProject, onOpenProject, onSaveProject }: QuickBarProps) {
  return (
    <div className="quick-bar">
      <button type="button" className="icon-btn" title="Nouveau" aria-label="Nouveau" onClick={onNewProject}>
        📄
      </button>
      <button type="button" className="icon-btn" title="Ouvrir .hydrops" aria-label="Ouvrir" onClick={onOpenProject}>
        📂
      </button>
      <button
        type="button"
        className="icon-btn"
        title="Enregistrer"
        aria-label="Enregistrer"
        onClick={onSaveProject}
        disabled={!projectOpen}
      >
        💾
      </button>
    </div>
  )
}
