// Barre d'acces rapide (cdc §4) : raccourcis icones vers les actions les plus frequentes de
// CHAQUE menu (consigne utilisateur : "prévoir les boutons menus aussi dans la barre d'outils
// sauf les menus Fichier et Variante") — Fichier/Variante restent des actions occasionnelles
// (nouveau/ouvrir/enregistrer un PROJET, gerer les variantes), deja couvertes par les 3 premiers
// boutons et le menu Variante. Aucune nouvelle logique ici : chaque bouton appelle exactement le
// meme handler que l'item de menu correspondant (cf. App.tsx).

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import type { LayoutMode } from './Workspace'

const LAYOUT_MODE_LABELS: Record<LayoutMode, string> = {
  mapOnly: 'Carte seule',
  profileOnly: 'Profil / Table',
  both: 'Vue combinée',
}

// Icone de la vue combinee (consigne utilisateur) : un carre coupe par la diagonale, moitie icone
// carte / moitie icone profil — plutot qu'un emoji generique (⬛) qui ne representait rien.
function LayoutModeIcon({ mode }: { mode: LayoutMode }) {
  if (mode === 'mapOnly') return <>🗺️</>
  if (mode === 'profileOnly') return <>📈</>
  return (
    <span className="layout-combo-icon" aria-hidden="true">
      <span className="layout-combo-icon-half layout-combo-icon-half--map">🗺️</span>
      <span className="layout-combo-icon-half layout-combo-icon-half--profile">📈</span>
    </span>
  )
}

// Bouton unique regroupant les 3 dispositions (consigne utilisateur : "consolidé dans un seul
// bouton [...] se déroule trois boutons sur la vertical") — remplace l'ancien groupe de 3 boutons
// toujours visibles. L'icone du bouton declencheur reflete la disposition active (defaut : vue
// combinée, cf. App.tsx:layoutMode).
function LayoutModeMenu({
  layoutMode,
  onLayoutModeChange,
}: {
  layoutMode: LayoutMode
  onLayoutModeChange: (mode: LayoutMode) => void
}) {
  const [open, setOpen] = useState(false)
  // Position calculee au clic (pas de repositionnement au scroll/resize : menu ephemere, ferme des
  // qu'on choisit une option ou clique ailleurs).
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (event: MouseEvent) => {
      const target = event.target as Node
      if (triggerRef.current?.contains(target)) return
      if (listRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [open])

  const handleToggle = () => {
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      setPosition({ top: rect.bottom + 4, left: rect.left })
    }
    setOpen((o) => !o)
  }

  return (
    <div className="layout-mode-menu">
      <button
        ref={triggerRef}
        type="button"
        className="icon-btn"
        title={`Disposition : ${LAYOUT_MODE_LABELS[layoutMode]}`}
        aria-label="Disposition de l'espace de travail"
        onClick={handleToggle}
      >
        <LayoutModeIcon mode={layoutMode} />
      </button>
      {open && position &&
        // Portail vers <body> (consigne : le menu doit se deployer visuellement, pas etre rogne) —
        // .quick-bar a un overflow-x: auto pour defiler horizontalement sur petit ecran, ce qui
        // force aussi son overflow-y calcule a "auto" (regle CSS Overflow §3.3) et rognerait un
        // menu deroulant enfant positionne en absolute. Le rendu hors de cet arbre DOM avec
        // position: fixed contourne le rognage.
        createPortal(
          <div
            ref={listRef}
            className="layout-mode-menu-list"
            style={{ position: 'fixed', top: position.top, left: position.left }}
          >
            {(Object.keys(LAYOUT_MODE_LABELS) as LayoutMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={`icon-btn ${mode === layoutMode ? 'active' : ''}`}
                title={LAYOUT_MODE_LABELS[mode]}
                aria-label={LAYOUT_MODE_LABELS[mode]}
                onClick={() => {
                  onLayoutModeChange(mode)
                  setOpen(false)
                }}
              >
                <LayoutModeIcon mode={mode} />
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  )
}

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

      <LayoutModeMenu layoutMode={layoutMode} onLayoutModeChange={onLayoutModeChange} />

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
