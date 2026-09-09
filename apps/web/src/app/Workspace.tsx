// Espace central adaptable (cdc §4) : Carte seule, Profil/Table seul, ou vue combinee avec
// separateur reglable — inspire de la page de reference fournie (carte en haut, profil en bas,
// glissiere verticale entre les deux plutot qu'un decoupage gauche/droite).

import { useCallback, useRef, useState } from 'react'

import { MapView } from '../features/map/MapView'
import { ProfileTableView } from '../features/profile/ProfileTableView'

export type LayoutMode = 'both' | 'mapOnly' | 'profileOnly'

const MIN_SPLIT = 30
const MAX_SPLIT = 80
const DEFAULT_SPLIT = 60

interface WorkspaceProps {
  layoutMode: LayoutMode
}

export function Workspace({ layoutMode }: WorkspaceProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [splitPercent, setSplitPercent] = useState(DEFAULT_SPLIT)
  const draggingRef = useRef(false)

  const applySplitFromClientY = useCallback((clientY: number) => {
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const percent = ((clientY - rect.top) / rect.height) * 100
    setSplitPercent(Math.min(MAX_SPLIT, Math.max(MIN_SPLIT, percent)))
  }, [])

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = true
    event.currentTarget.setPointerCapture(event.pointerId)
    applySplitFromClientY(event.clientY)
  }

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (draggingRef.current) applySplitFromClientY(event.clientY)
  }

  const stopDragging = () => {
    draggingRef.current = false
  }

  return (
    <div className="workspace">
      <div
        ref={containerRef}
        className={`workspace-split layout-${layoutMode}`}
        style={{ '--split-top': `${splitPercent}%` } as React.CSSProperties}
      >
        <section className="panel panel--map">
          <MapView />
        </section>

        <div
          className="divider"
          role="separator"
          aria-orientation="horizontal"
          aria-label="Ajuster la hauteur du profil"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={stopDragging}
          onPointerCancel={stopDragging}
        >
          <div className="divider-handle" />
        </div>

        <section className="panel panel--profile">
          <ProfileTableView />
        </section>
      </div>
    </div>
  )
}
