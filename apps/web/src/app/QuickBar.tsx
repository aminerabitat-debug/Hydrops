// Barre d'acces rapide (cdc §4) : raccourcis icones vers les actions les plus frequentes de
// CHAQUE menu (consigne utilisateur : "prévoir les boutons menus aussi dans la barre d'outils
// sauf les menus Fichier et Variante") — Fichier/Variante restent des actions occasionnelles
// (nouveau/ouvrir/enregistrer un PROJET, gerer les variantes), deja couvertes par les 3 premiers
// boutons et le menu Variante. Aucune nouvelle logique ici : chaque bouton appelle exactement le
// meme handler que l'item de menu correspondant (cf. App.tsx).

import type { LayoutMode } from './Workspace'

interface QuickBarProps {
  projectOpen: boolean
  variantSelected: boolean
  onNewProject: () => void
  onOpenProject: () => void
  onSaveProject: () => void
  onRunCalcul: () => void
  onOpenPreferences: () => void
  onOpenConduites: () => void
  layoutMode: LayoutMode
  onLayoutModeChange: (mode: LayoutMode) => void
  onAbout: () => void
}

export function QuickBar({
  projectOpen,
  variantSelected,
  onNewProject,
  onOpenProject,
  onSaveProject,
  onRunCalcul,
  onOpenPreferences,
  onOpenConduites,
  layoutMode,
  onLayoutModeChange,
  onAbout,
}: QuickBarProps) {
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

      <span className="quick-bar-sep" aria-hidden="true" />

      <button
        type="button"
        className="icon-btn"
        title="Calculer"
        aria-label="Calculer"
        onClick={onRunCalcul}
        disabled={!variantSelected}
      >
        🧮
      </button>
      <button
        type="button"
        className="icon-btn"
        title="Préférences de calcul"
        aria-label="Préférences de calcul"
        onClick={onOpenPreferences}
        disabled={!projectOpen}
      >
        ⚙️
      </button>

      <span className="quick-bar-sep" aria-hidden="true" />

      <button type="button" className="icon-btn" title="Base de données — Conduites" aria-label="Conduites" onClick={onOpenConduites}>
        🗄️
      </button>

      <span className="quick-bar-sep" aria-hidden="true" />

      <div className="quick-bar-segment" role="group" aria-label="Disposition de l'espace de travail">
        <button
          type="button"
          className={`icon-btn ${layoutMode === 'mapOnly' ? 'active' : ''}`}
          title="Carte seule"
          aria-label="Carte seule"
          onClick={() => onLayoutModeChange('mapOnly')}
        >
          🗺️
        </button>
        <button
          type="button"
          className={`icon-btn ${layoutMode === 'profileOnly' ? 'active' : ''}`}
          title="Profil / Table"
          aria-label="Profil / Table"
          onClick={() => onLayoutModeChange('profileOnly')}
        >
          📈
        </button>
        <button
          type="button"
          className={`icon-btn ${layoutMode === 'both' ? 'active' : ''}`}
          title="Vue combinée"
          aria-label="Vue combinée"
          onClick={() => onLayoutModeChange('both')}
        >
          ⬛
        </button>
      </div>

      <span className="quick-bar-sep" aria-hidden="true" />

      <button type="button" className="icon-btn" title="Langue (Français) — Anglais disponible au Lot 7" aria-label="Langue" disabled>
        🌐
      </button>
      <button type="button" className="icon-btn" title="À propos" aria-label="À propos" onClick={onAbout}>
        ❓
      </button>
    </div>
  )
}
