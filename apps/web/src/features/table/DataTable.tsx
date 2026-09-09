// Table principale (cdc §7) — une ligne par PIQUET du profil (echantillon DEM), pas seulement les
// noeuds : c'est la table "profil en long" classique en genie civil, les noeuds n'etant que des
// points particuliers marques dessus (colonne Type, vide sinon). Chaque piquet porte un numero
// unique, incremente, stable (attribue avant le filtrage par troncon — un piquet donne garde son
// numero quelle que soit la vue, consigne utilisateur). Portee pilotee par la selection dans
// l'arborescence (state.selection.tableScope, cf. store.ts) :
//   - Tracé sélectionné : tous les piquets, colonnes topo uniquement.
//   - Tronçon sélectionné : piquets de sa plage de PK, + colonnes conduite (le materiau/DN/etc.
//     provient du segment reel qui couvre chaque piquet — un troncon peut regrouper plusieurs
//     segments de DN differents si des jonctions/piquages s'y trouvent, decision utilisateur).
// On peut positionner/editer un noeud directement depuis cette vue (pas seulement le profil,
// consigne utilisateur), y compris sur une extremite de trace. Quand le mode "+ Nœud" (bascule
// commune avec le profil, cf. ProfileTableView) est actif, cliquer n'importe ou sur une ligne sans
// noeud l'ajoute directement (pas seulement le petit bouton "+") — meme logique que le clic sur le
// profil en Mode Graphique (consigne utilisateur). Largeurs de colonnes ajustables a la souris ;
// TanStack Table/virtualisation restent differes tant que la taille reelle des reseaux testes ne
// l'impose pas.

import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../shared/apiClient'
import { buildVertices, interpolateLonLatAtPk } from '../../shared/geo'
import { isPlaceholderNode, nodeDisplayLabel } from '../../shared/nodeLabels'
import { useAppStore } from '../../state/store'
import type { CatalogMaterial, Node, Segment } from '../../shared/types'

const SNAP_TOLERANCE_M = 0.5

interface Row {
  piquetNumber: number
  pk: number
  x: number
  y: number
  z: number
  node: Node | null
  partialDistance: number
}

const TOPO_COLUMNS = ['N° Piquet', 'Type', 'Distance partielle (m)', 'PK cumulé (m)', 'X', 'Y', 'Z (m)']
const PIPE_COLUMNS = ['Matériau', 'DN', 'Classe', 'DI (mm)', 'Rugosité (mm)']
const ACTION_COLUMN = ''

const DEFAULT_COLUMN_WIDTHS: Record<string, number> = {
  'N° Piquet': 80, Type: 120, 'Distance partielle (m)': 150, 'PK cumulé (m)': 120,
  X: 110, Y: 110, 'Z (m)': 90,
  Matériau: 140, DN: 70, Classe: 80, 'DI (mm)': 80, 'Rugosité (mm)': 100,
  '': 60,
}
const MIN_COLUMN_WIDTH = 36

interface DataTableProps {
  onAddNode: (pk: number) => void
  onEditNode: (node: Node) => void
  onAssignNode: (node: Node) => void
  onDeleteNode: (node: Node) => void
  addNodeMode: boolean
}

export function DataTable({ onAddNode, onEditNode, onAssignNode, onDeleteNode, addNodeMode }: DataTableProps) {
  const traces = useAppStore((s) => s.traces)
  const nodes = useAppStore((s) => s.nodes)
  const segments = useAppStore((s) => s.segments)
  const selectedTraceId = useAppStore((s) => s.selection.selectedTraceId)
  const tableScope = useAppStore((s) => s.selection.tableScope)
  const hoveredPk = useAppStore((s) => s.selection.hoveredPk)
  const setHoveredPk = useAppStore((s) => s.setHoveredPk)

  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(DEFAULT_COLUMN_WIDTHS)
  const resizingRef = useRef<{ key: string; startX: number; startWidth: number } | null>(null)

  const [materials, setMaterials] = useState<CatalogMaterial[]>([])

  useEffect(() => {
    api.listCatalogMaterials().then(setMaterials).catch(() => setMaterials([]))
  }, [])

  const trace = traces.find((t) => t.id === selectedTraceId) ?? traces[0]
  const profile = trace?.elevation_profile

  const columns = useMemo(
    () => (tableScope.kind === 'troncon' ? [...TOPO_COLUMNS, ...PIPE_COLUMNS, ACTION_COLUMN] : [...TOPO_COLUMNS, ACTION_COLUMN]),
    [tableScope.kind],
  )

  const rows = useMemo<Row[]>(() => {
    if (!trace || !profile || profile.raw.length === 0) return []
    const traceNodes = nodes.filter((n) => n.trace_id === trace.id)
    const vertices = buildVertices(trace.geometry.coordinates as [number, number][])

    const merged = new Map<number, { pk: number; z: number; node: Node | null }>()
    for (const p of profile.raw) merged.set(p.pk, { pk: p.pk, z: p.z, node: null })

    for (const node of traceNodes) {
      let nearestPk: number | null = null
      let nearestDist = Infinity
      for (const pk of merged.keys()) {
        const d = Math.abs(pk - node.pk)
        if (d < nearestDist) {
          nearestDist = d
          nearestPk = pk
        }
      }
      if (nearestPk != null && nearestDist <= SNAP_TOLERANCE_M) {
        merged.set(nearestPk, { pk: nearestPk, z: node.z, node })
      } else {
        merged.set(node.pk, { pk: node.pk, z: node.z, node })
      }
    }

    // Numero de piquet attribue sur la liste COMPLETE et triee, avant tout filtrage par troncon —
    // un piquet garde le meme numero quelle que soit la vue (indexe, incremente, unique).
    const fullSorted = Array.from(merged.values()).sort((a, b) => a.pk - b.pk)
    const numbered = fullSorted.map((r, i) => ({ ...r, piquetNumber: i + 1 }))

    let filtered = numbered
    if (tableScope.kind === 'troncon') {
      filtered = numbered.filter((r) => r.pk >= tableScope.pkStart - 1e-6 && r.pk <= tableScope.pkEnd + 1e-6)
    }

    return filtered.map((r, i) => {
      const [lon, lat] = r.node ? [r.node.x, r.node.y] : interpolateLonLatAtPk(vertices, r.pk)
      return {
        piquetNumber: r.piquetNumber,
        pk: r.pk,
        x: lon,
        y: lat,
        z: r.z,
        node: r.node,
        partialDistance: i === 0 ? 0 : r.pk - filtered[i - 1].pk,
      }
    })
  }, [trace, profile, nodes, tableScope])

  const segmentAtPk = (pk: number): Segment | null => segments.find((s) => s.pk_start - 1e-6 <= pk && pk <= s.pk_end + 1e-6) ?? null

  const handleResizeMove = (event: PointerEvent) => {
    const resizing = resizingRef.current
    if (!resizing) return
    const delta = event.clientX - resizing.startX
    const nextWidth = Math.max(MIN_COLUMN_WIDTH, resizing.startWidth + delta)
    setColumnWidths((widths) => ({ ...widths, [resizing.key]: nextWidth }))
  }

  const handleResizeEnd = () => {
    resizingRef.current = null
    document.removeEventListener('pointermove', handleResizeMove)
    document.removeEventListener('pointerup', handleResizeEnd)
  }

  const handleResizeStart = (key: string) => (event: React.PointerEvent) => {
    event.preventDefault()
    resizingRef.current = { key, startX: event.clientX, startWidth: columnWidths[key] ?? 100 }
    document.addEventListener('pointermove', handleResizeMove)
    document.addEventListener('pointerup', handleResizeEnd)
  }

  if (!trace) return <p className="empty-hint">Aucune trace selectionnee.</p>
  if (rows.length === 0) return <p className="empty-hint">Profil non disponible pour cette trace.</p>

  return (
    <div className="data-table-container">
      <table className="data-table" style={{ tableLayout: 'fixed' }}>
        <colgroup>
          {columns.map((label, i) => (
            <col key={label || `col-${i}`} style={{ width: columnWidths[label] ?? 100 }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((label, i) => (
              <th key={label || `h-${i}`}>
                {label}
                <span
                  className="col-resize-handle"
                  onPointerDown={handleResizeStart(label)}
                  onClick={(e) => e.stopPropagation()}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const segment = tableScope.kind === 'troncon' ? segmentAtPk(row.pk) : null
            const materialLabel = segment ? materials.find((m) => m.material === segment.material)?.label ?? segment.material : '—'
            // Un placeholder d'extremite pas encore affectee (noeud "junction") se comporte comme un
            // piquet vide : pas de Type affiche, icone "+" plutot que crayon/corbeille, et
            // participe au clic-de-ligne du mode "+ Nœud" — consigne utilisateur.
            const hasRealNode = row.node != null && !isPlaceholderNode(row.node)
            const addableByRowClick = addNodeMode && !hasRealNode
            const rowClasses = [
              hoveredPk != null && Math.abs(row.pk - hoveredPk) < 1 ? 'row-hovered' : '',
              addableByRowClick ? 'row-addable' : '',
            ]
              .filter(Boolean)
              .join(' ')
            const handleRowAdd = () => (row.node ? onAssignNode(row.node) : onAddNode(row.pk))
            return (
              <tr
                key={row.piquetNumber}
                className={rowClasses}
                onMouseEnter={() => setHoveredPk(row.pk)}
                onMouseLeave={() => setHoveredPk(null)}
                onClick={addableByRowClick ? handleRowAdd : undefined}
                title={addableByRowClick ? 'Cliquer pour ajouter un nœud à ce piquet' : undefined}
              >
                <td>{row.piquetNumber}</td>
                <td>{hasRealNode ? nodeDisplayLabel(row.node!) : ''}</td>
                <td>{row.partialDistance.toFixed(1)}</td>
                <td>{row.pk.toFixed(1)}</td>
                <td>{row.x.toFixed(6)}</td>
                <td>{row.y.toFixed(6)}</td>
                <td>{row.z.toFixed(2)}</td>
                {tableScope.kind === 'troncon' && (
                  <>
                    <td>{materialLabel}</td>
                    <td>{segment ? segment.dn : '—'}</td>
                    <td>{segment ? segment.pressure_class.toUpperCase() : '—'}</td>
                    <td>{segment ? segment.di.toFixed(1) : '—'}</td>
                    <td>{segment ? segment.roughness.toFixed(3) : '—'}</td>
                  </>
                )}
                <td className="data-table-actions">
                  {hasRealNode ? (
                    <>
                      <button
                        type="button"
                        className="btn-row-icon"
                        title="Éditer ce nœud (type, nom)"
                        onClick={(e) => {
                          e.stopPropagation()
                          onEditNode(row.node!)
                        }}
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        className="btn-row-icon"
                        title="Supprimer ce nœud"
                        onClick={(e) => {
                          e.stopPropagation()
                          onDeleteNode(row.node!)
                        }}
                      >
                        🗑
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="btn-row-icon"
                      title="Ajouter un nœud à ce piquet"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleRowAdd()
                      }}
                    >
                      +
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
