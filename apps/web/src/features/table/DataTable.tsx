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
  // Piquet "bis" (consigne utilisateur : ajout d'un ouvrage, ou changement de DN/PN/materiau —
  // deux segments DIFFERENTS peuvent se rejoindre au meme PK cumule) : duplique le piquet pour
  // afficher les valeurs AVANT (piquet d'origine, segment qui se termine ici) ET APRES (piquet
  // "bis", segment qui commence ici) sans ambiguite — jamais persiste, recalcule a chaque rendu
  // (donc "supprime" des que la condition ne tient plus, et regenere des qu'elle tient a nouveau,
  // y compris apres un nouveau calcul qui changerait les DN de part et d'autre).
  isBis: boolean
}

const TOPO_COLUMNS = ['N° Piquet', 'Type', 'Distance partielle (m)', 'PK cumulé (m)', 'X', 'Y', 'Z (m)']
const PIPE_COLUMNS = ['Matériau', 'DN', 'Classe', 'DI (mm)', 'Rugosité (mm)']
// Sorties du bouton Calcul > Calculer (consigne utilisateur) : rappel du debit, vitesse, PDC
// unitaire/lineaire/totale, puis les lignes piezometrique et hydrostatique (si applicable) pour
// chaque piquet du troncon selectionne — '—' tant qu'aucun calcul n'a ete lance pour ce segment/
// noeud (cf. Segment.velocity/Node.piezo_head, null jusqu'au premier calcul) : ces colonnes ne
// sont JAMAIS prereplies d'une valeur par defaut, et sont explicitement reinitialisees des que les
// donnees du troncon changent (cf. routers/network.py:_reset_node_calc_fields).
const HYDRAULIC_COLUMNS = [
  'Débit (m³/h)', 'Vitesse (m/s)', 'PDC unitaire (m/km)', 'PDC linéaire (m)', 'PDC totale (m)',
  'Cote piézo (m)', 'Pression dyn. (m)', 'Pression hydro. max (m)', 'Pression hydro. min (m)',
]
const ACTION_COLUMN = ''

const DEFAULT_COLUMN_WIDTHS: Record<string, number> = {
  'N° Piquet': 80, Type: 120, 'Distance partielle (m)': 150, 'PK cumulé (m)': 120,
  X: 110, Y: 110, 'Z (m)': 90,
  Matériau: 140, DN: 70, Classe: 80, 'DI (mm)': 80, 'Rugosité (mm)': 100,
  'Débit (m³/h)': 110, 'Vitesse (m/s)': 100, 'PDC unitaire (m/km)': 130, 'PDC linéaire (m)': 120,
  'PDC totale (m)': 110, 'Cote piézo (m)': 110, 'Pression dyn. (m)': 120,
  'Pression hydro. max (m)': 140, 'Pression hydro. min (m)': 140,
  '': 60,
}

function formatOrDash(value: number | null | undefined, digits = 2): string {
  return value == null ? '—' : value.toFixed(digits)
}

// Cote (piezometrique ou hydrostatique) au piquet `pk`, interpolee lineairement entre les deux
// noeuds reels qui bornent son segment — la perte de charge est constante le long d'un segment (DN/
// materiau fixes), donc la cote y varie bien lineairement avec la distance (consigne utilisateur :
// ces colonnes doivent etre calculees pour CHAQUE piquet, pas seulement aux noeuds).
function interpolateNodeField(
  pk: number,
  segment: Segment,
  nodesById: Map<string, Node>,
  field: 'piezo_head' | 'pressure_dynamic' | 'pressure_static_max' | 'pressure_static_min',
): number | null {
  const a = nodesById.get(segment.upstream_node_id)?.[field]
  const b = nodesById.get(segment.downstream_node_id)?.[field]
  if (a == null || b == null) return null
  const span = segment.pk_end - segment.pk_start
  if (span <= 1e-9) return a
  const t = (pk - segment.pk_start) / span
  return a + t * (b - a)
}

interface HydraulicValues {
  calculated: boolean
  flow: number | null
  velocity: number | null
  pdcUnitKm: number | null
  pdcLineaire: number | null
  pdcTotale: number | null
  piezo: number | null
  pressureDyn: number | null
  pressureStaticMax: number | null
  pressureStaticMin: number | null
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
    () =>
      tableScope.kind === 'troncon'
        ? [...TOPO_COLUMNS, ...PIPE_COLUMNS, ...HYDRAULIC_COLUMNS, ACTION_COLUMN]
        : [...TOPO_COLUMNS, ACTION_COLUMN],
    [tableScope.kind],
  )

  // Segment qui se TERMINE / COMMENCE exactement a ce PK (bornes de segment, pas juste "le
  // contient") — distingue sans ambiguite le "avant"/"après" a un piquet frontiere entre deux
  // segments (consigne utilisateur, cf. Row.isBis), la ou l'ancien segmentAtPk (qui contient le
  // pk) pouvait retourner arbitrairement l'un ou l'autre des deux a la frontiere exacte.
  const segmentEndingAt = (pk: number): Segment | null => segments.find((s) => Math.abs(s.pk_end - pk) < 1e-6) ?? null
  const segmentStartingAt = (pk: number): Segment | null => segments.find((s) => Math.abs(s.pk_start - pk) < 1e-6) ?? null

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

    const fullSorted = Array.from(merged.values()).sort((a, b) => a.pk - b.pk)

    // Piquet "bis" (consigne utilisateur) : a tout ouvrage REEL qui n'est pas une extremite de
    // trace (donc toujours frontiere entre deux segments distincts — celui qui se termine et
    // celui qui commence ici, potentiellement de DN/materiau/classe differents une fois calcules)
    // — un ouvrage placeholder ("junction" pas encore affecte) n'en a jamais. Duplique juste APRES
    // le piquet d'origine, distance partielle 0 (meme PK cumule).
    const expanded: { pk: number; z: number; node: Node | null; isBis: boolean }[] = []
    for (const entry of fullSorted) {
      expanded.push({ ...entry, isBis: false })
      if (!entry.node || isPlaceholderNode(entry.node)) continue
      const before = segmentEndingAt(entry.pk)
      const after = segmentStartingAt(entry.pk)
      if (!before || !after) continue // extremite de trace : un seul cote, pas de "bis"
      expanded.push({ pk: entry.pk, z: entry.z, node: entry.node, isBis: true })
    }

    // Numero de piquet attribue sur la liste COMPLETE et triee (bis inclus), avant tout filtrage
    // par troncon — un piquet garde le meme numero quelle que soit la vue (indexe, incremente,
    // unique) ; un "bis" en fait partie integrante (ephemere : il disparait/reapparait selon
    // isPlaceholderNode/pipeChanged, jamais un numero fige a l'avance).
    const numbered = expanded.map((r, i) => ({ ...r, piquetNumber: i + 1 }))

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
        isBis: r.isBis,
        partialDistance: i === 0 ? 0 : r.pk - filtered[i - 1].pk,
      }
    })
  }, [trace, profile, nodes, segments, tableScope])

  const segmentAtPk = (pk: number): Segment | null => segments.find((s) => s.pk_start - 1e-6 <= pk && pk <= s.pk_end + 1e-6) ?? null

  // Pour un piquet AVANT/APRES (cf. Row.isBis) : segment explicite plutot que segmentAtPk (qui
  // choisirait arbitrairement l'un des deux a la frontiere exacte) — pour un piquet ordinaire
  // (aucun segment ne se termine/commence exactement ici), retombe sur segmentAtPk inchange.
  const segmentForRow = (row: { pk: number; isBis: boolean }): Segment | null => {
    if (row.isBis) return segmentStartingAt(row.pk)
    return segmentEndingAt(row.pk) ?? segmentAtPk(row.pk)
  }

  const nodesById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  // PDC lineaire (consigne utilisateur) = perte du SEGMENT repartie au prorata de la distance
  // partielle du piquet (pas la perte totale du segment recopiee sur chaque ligne) ; PDC totale =
  // cumul de cette valeur depuis le debut du troncon affiche (toujours le pk_start du troncon,
  // cf. ProjectTree:handleSelectTroncon). Cote piezo/pressions interpolees par piquet (ci-dessus).
  const hydraulicRows = useMemo<HydraulicValues[]>(() => {
    if (tableScope.kind !== 'troncon') return []
    let cumulative = 0
    return rows.map((row) => {
      const segment = segmentForRow(row)
      if (!segment) {
        return {
          calculated: false,
          flow: null, velocity: null, pdcUnitKm: null, pdcLineaire: null, pdcTotale: null,
          piezo: null, pressureDyn: null, pressureStaticMax: null, pressureStaticMin: null,
        }
      }
      const calculated = segment.velocity != null
      const pdcUnitKm = segment.head_loss_unit != null ? segment.head_loss_unit * 1000 : null
      const rate = segment.length > 1e-9 && segment.head_loss_segment != null ? segment.head_loss_segment / segment.length : null
      const pdcLineaire = rate != null ? rate * row.partialDistance : null
      if (pdcLineaire != null) cumulative += pdcLineaire
      return {
        calculated,
        flow: calculated ? segment.flow : null,
        velocity: segment.velocity ?? null,
        pdcUnitKm,
        pdcLineaire,
        pdcTotale: pdcLineaire != null ? cumulative : null,
        piezo: interpolateNodeField(row.pk, segment, nodesById, 'piezo_head'),
        pressureDyn: interpolateNodeField(row.pk, segment, nodesById, 'pressure_dynamic'),
        pressureStaticMax: interpolateNodeField(row.pk, segment, nodesById, 'pressure_static_max'),
        pressureStaticMin: interpolateNodeField(row.pk, segment, nodesById, 'pressure_static_min'),
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, segments, nodesById, tableScope.kind])

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
          {rows.map((row, rowIndex) => {
            const segment = tableScope.kind === 'troncon' ? segmentForRow(row) : null
            const hydraulics = hydraulicRows[rowIndex]
            // Materiau/DN/Classe/DI/Rugosite ne doivent etre affiches QUE si le calcul a abouti
            // pour ce segment (consigne utilisateur) — sinon le catalogue par defaut (jamais
            // "vide") donnerait l'impression trompeuse d'un dimensionnement valide.
            const pipeCalculated = hydraulics?.calculated ?? false
            const materialLabel =
              segment && pipeCalculated ? materials.find((m) => m.material === segment.material)?.label ?? segment.material : '—'
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
                <td>{hasRealNode ? nodeDisplayLabel(row.node!) + (row.isBis ? ' (bis)' : '') : ''}</td>
                <td>{row.partialDistance.toFixed(1)}</td>
                <td>{row.pk.toFixed(1)}</td>
                <td>{row.x.toFixed(6)}</td>
                <td>{row.y.toFixed(6)}</td>
                <td>{row.z.toFixed(2)}</td>
                {tableScope.kind === 'troncon' && (
                  <>
                    <td>{materialLabel}</td>
                    <td>{segment && pipeCalculated ? segment.dn : '—'}</td>
                    <td>{segment && pipeCalculated ? segment.pressure_class.toUpperCase() : '—'}</td>
                    <td>{segment && pipeCalculated ? segment.di.toFixed(1) : '—'}</td>
                    <td>{segment && pipeCalculated ? segment.roughness.toFixed(3) : '—'}</td>
                    <td>{formatOrDash(hydraulics?.flow, 1)}</td>
                    <td>{formatOrDash(hydraulics?.velocity, 2)}</td>
                    <td>{formatOrDash(hydraulics?.pdcUnitKm, 2)}</td>
                    <td>{formatOrDash(hydraulics?.pdcLineaire, 3)}</td>
                    <td>{formatOrDash(hydraulics?.pdcTotale, 3)}</td>
                    <td>{formatOrDash(hydraulics?.piezo, 2)}</td>
                    <td>{formatOrDash(hydraulics?.pressureDyn, 2)}</td>
                    <td>{formatOrDash(hydraulics?.pressureStaticMax, 2)}</td>
                    <td>{formatOrDash(hydraulics?.pressureStaticMin, 2)}</td>
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
