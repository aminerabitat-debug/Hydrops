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
import { crossingDisplayText, crossingLength } from '../../shared/crossingColors'
import { buildVertices, interpolateLonLatAtPk } from '../../shared/geo'
import { isPlaceholderNode, nodeDisplayLabel } from '../../shared/nodeLabels'
import { useAppStore } from '../../state/store'
import type { CatalogMaterial, Crossing, Node, Segment, SegmentDetail } from '../../shared/types'

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

const TOPO_COLUMNS = [
  'N° Piquet', 'Type', 'Distance partielle (m)', 'PK cumulé (m)', 'X', 'Y', 'Z (m)', 'Traversée',
  'Longueur de la traversée (m)',
]
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
  X: 110, Y: 110, 'Z (m)': 90, 'Traversée': 170, 'Longueur de la traversée (m)': 160,
  Matériau: 140, DN: 70, Classe: 80, 'DI (mm)': 80, 'Rugosité (mm)': 100,
  'Débit (m³/h)': 110, 'Vitesse (m/s)': 100, 'PDC unitaire (m/km)': 130, 'PDC linéaire (m)': 120,
  'PDC totale (m)': 110, 'Cote piézo (m)': 110, 'Pression dyn. (m)': 120,
  'Pression hydro. max (m)': 140, 'Pression hydro. min (m)': 140,
  '': 60,
}

function formatOrDash(value: number | null | undefined, digits = 2): string {
  return value == null ? '—' : value.toFixed(digits)
}

// Cote (piezometrique ou hydrostatique) au piquet `pk`. Le DN n'est plus forcement constant le
// long d'un segment (tableau par piquet, glossaire Piquet/Segment/Troncon — telescopage), donc une
// simple interpolation lineaire entre les deux noeuds reels sous/sur-estime la cote piezometrique
// en cours de route (constate concretement sur un cas reel). Quand `segment.segment_details` est
// disponible, la cote piezo/pression dynamique est reconstruite piquet par piquet a partir de la
// cote DEJA CONNUE du noeud reel aval et de la perte de charge cumulee relative de chaque piquet —
// aucune nouvelle donnee moteur necessaire.
// Les pressions HYDROSTATIQUES (max/min) souffrent du meme defaut pour une autre raison : le niveau
// du reservoir est bien constant, mais `pressure_static_max/min = niveau - altitude du TERRAIN`, et
// le terrain n'est generalement pas rectiligne entre les deux noeuds reels — interpoler ces valeurs
// LINEAIREMENT (comme avant) est donc tout aussi faux qu'interpoler la cote piezo. Le niveau
// constant est recupere depuis le noeud aval (deja calcule : `pressure_static_max + z du noeud` =
// le niveau), puis applique directement a l'altitude REELLE de ce piquet (`rowZ`, deja connue,
// aucune interpolation necessaire).
function interpolateNodeField(
  pk: number,
  segment: Segment,
  nodesById: Map<string, Node>,
  field: 'piezo_head' | 'pressure_dynamic' | 'pressure_static_max' | 'pressure_static_min',
  rowZ?: number,
): number | null {
  if ((field === 'piezo_head' || field === 'pressure_dynamic') && segment.segment_details && segment.segment_details.length > 1 && rowZ != null) {
    const downstreamPiezo = nodesById.get(segment.downstream_node_id)?.piezo_head
    const details = segment.segment_details
    const lastCumulative = details[details.length - 1].head_loss_cumulative
    if (downstreamPiezo != null && lastCumulative != null) {
      const detail = details.find((d) => d.pk >= pk - 1e-6) ?? details[details.length - 1]
      if (detail.head_loss_cumulative != null) {
        const piezo = downstreamPiezo + (lastCumulative - detail.head_loss_cumulative)
        return field === 'piezo_head' ? piezo : piezo - rowZ
      }
    }
  }
  if ((field === 'pressure_static_max' || field === 'pressure_static_min') && rowZ != null) {
    const downstreamNode = nodesById.get(segment.downstream_node_id)
    const downstreamValue = downstreamNode?.[field]
    if (downstreamNode != null && downstreamValue != null) {
      const constantLevel = downstreamValue + downstreamNode.z
      return constantLevel - rowZ
    }
  }
  const a = nodesById.get(segment.upstream_node_id)?.[field]
  const b = nodesById.get(segment.downstream_node_id)?.[field]
  if (a == null || b == null) return null
  const span = segment.pk_end - segment.pk_start
  if (span <= 1e-9) return a
  const t = (pk - segment.pk_start) / span
  return a + t * (b - a)
}

// Segment FIN (glossaire Piquet/Segment/Troncon) qui couvre le piquet `pk` — le premier dont le pk
// (piquet aval de ce segment fin) est >= `pk`, meme convention que segmentEndingAt/segmentForRow
// (attribution au piquet aval), generalisee au tableau par piquet. Repli sur le dernier element si
// `pk` depasse le dernier piquet enregistre (bord flottant). `null` si pas encore calcule.
function segmentDetailForRow(segment: Segment | null, pk: number): SegmentDetail | null {
  const details = segment?.segment_details
  if (!details || details.length === 0) return null
  return details.find((d) => d.pk >= pk - 1e-6) ?? details[details.length - 1]
}

// Longueur du segment fin qui se termine a `detail.pk` — pour repartir sa PROPRE perte de charge
// (et non celle moyennee sur tout le Segment/troncon) au prorata de la distance partielle d'un
// piquet DataTable (consigne utilisateur : DN/pertes de charge varient desormais par piquet).
function segmentDetailLength(segment: Segment, detail: SegmentDetail): number {
  const details = segment.segment_details ?? []
  const idx = details.indexOf(detail)
  const startPk = idx <= 0 ? segment.pk_start : details[idx - 1].pk
  return detail.pk - startPk
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
  const pkPickResolver = useAppStore((s) => s.pkPickResolver)
  const resolvePkPick = useAppStore((s) => s.resolvePkPick)
  const profileFocusRequest = useAppStore((s) => s.profileFocusRequest)

  const [columnWidths, setColumnWidths] = useState<Record<string, number>>(DEFAULT_COLUMN_WIDTHS)
  const resizingRef = useRef<{ key: string; startX: number; startWidth: number } | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

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

  // Synchronisation zoom carte -> table (consigne utilisateur, cf. MapView.tsx qui emet cette
  // demande en Vue combinée) — fait defiler la ligne la plus proche du CENTRE de la plage visible
  // au milieu du conteneur, meme si la table n'est pas la vue active du moment (Mode Graphique) :
  // elle sera deja au bon endroit si l'utilisateur bascule ensuite en Mode Data.
  useEffect(() => {
    if (!profileFocusRequest || rows.length === 0 || !containerRef.current) return
    const center = (profileFocusRequest.pkStart + profileFocusRequest.pkEnd) / 2
    let closest = rows[0]
    let bestDist = Math.abs(closest.pk - center)
    for (const r of rows) {
      const d = Math.abs(r.pk - center)
      if (d < bestDist) {
        bestDist = d
        closest = r
      }
    }
    const rowEl = containerRef.current.querySelector<HTMLTableRowElement>(`tr[data-pk="${closest.pk}"]`)
    rowEl?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [profileFocusRequest, rows])

  // Traversées détectées (consigne utilisateur : colonne dédiée dans le profil Data) — rattachées
  // au piquet le plus proche (leur PK exact vient d'une projection géométrique, pas forcément
  // aligné sur la grille d'échantillonnage des piquets), jamais à deux piquets à la fois.
  const crossingsByRowPk = useMemo(() => {
    const map = new Map<number, Crossing[]>()
    if (!trace?.crossings || trace.crossings.length === 0 || rows.length === 0) return map
    for (const crossing of trace.crossings) {
      let closestPk = rows[0].pk
      let bestDist = Math.abs(closestPk - crossing.pk)
      for (const r of rows) {
        const d = Math.abs(r.pk - crossing.pk)
        if (d < bestDist) {
          bestDist = d
          closestPk = r.pk
        }
      }
      const list = map.get(closestPk) ?? []
      list.push(crossing)
      map.set(closestPk, list)
    }
    return map
  }, [trace?.crossings, rows])

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
      // Segment FIN (piquet par piquet, cf. glossaire) qui couvre ce piquet, s'il a ete calcule —
      // repli sur les champs scalaires du Segment/troncon (calcul non encore lance, ou pipe force,
      // toujours homogene) sinon.
      const detail = segmentDetailForRow(segment, row.pk)
      const effectiveVelocity = detail ? detail.velocity : segment.velocity
      const effectiveHeadLossUnit = detail ? detail.head_loss_unit : segment.head_loss_unit
      const effectiveHeadLossSegment = detail ? detail.head_loss_segment : segment.head_loss_segment
      const effectiveLength = detail ? segmentDetailLength(segment, detail) : segment.length
      const calculated = effectiveVelocity != null
      const pdcUnitKm = effectiveHeadLossUnit != null ? effectiveHeadLossUnit * 1000 : null
      const rate = effectiveLength > 1e-9 && effectiveHeadLossSegment != null ? effectiveHeadLossSegment / effectiveLength : null
      const pdcLineaire = rate != null ? rate * row.partialDistance : null
      if (pdcLineaire != null) cumulative += pdcLineaire
      return {
        calculated,
        flow: calculated ? segment.flow : null,
        velocity: effectiveVelocity ?? null,
        pdcUnitKm,
        pdcLineaire,
        pdcTotale: pdcLineaire != null ? cumulative : null,
        piezo: interpolateNodeField(row.pk, segment, nodesById, 'piezo_head', row.z),
        pressureDyn: interpolateNodeField(row.pk, segment, nodesById, 'pressure_dynamic', row.z),
        pressureStaticMax: interpolateNodeField(row.pk, segment, nodesById, 'pressure_static_max', row.z),
        pressureStaticMin: interpolateNodeField(row.pk, segment, nodesById, 'pressure_static_min', row.z),
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
    <div className="data-table-container" ref={containerRef}>
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
            // "vide") donnerait l'impression trompeuse d'un dimensionnement valide. Le detail PAR
            // PIQUET (glossaire Piquet/Segment/Troncon) prime sur les champs scalaires du Segment
            // quand il est disponible — un troncon peut telescoper le DN vers l'aval.
            const pipeCalculated = hydraulics?.calculated ?? false
            const pipeDetail = segment ? segmentDetailForRow(segment, row.pk) : null
            const pipeMaterial = pipeDetail?.material ?? segment?.material
            const pipeDn = pipeDetail?.dn ?? segment?.dn
            const pipePressureClass = pipeDetail?.pressure_class ?? segment?.pressure_class
            const pipeDi = pipeDetail?.di ?? segment?.di
            const pipeRoughness = pipeDetail?.roughness ?? segment?.roughness
            const materialLabel =
              segment && pipeCalculated && pipeMaterial != null
                ? materials.find((m) => m.material === pipeMaterial)?.label ?? pipeMaterial
                : '—'
            // Un placeholder d'extremite pas encore affectee (noeud "junction") se comporte comme un
            // piquet vide : pas de Type affiche, icone "+" plutot que crayon/corbeille, et
            // participe au clic-de-ligne du mode "+ Nœud" — consigne utilisateur.
            const hasRealNode = row.node != null && !isPlaceholderNode(row.node)
            const addableByRowClick = addNodeMode && !hasRealNode
            // Selection de PK en cours (consigne utilisateur : bouton "…" du panneau Contraintes
            // de la fenetre Tronçon) — n'importe quelle ligne resout alors le PK vise, prioritaire
            // sur le mode "+ Nœud".
            const pickableByRowClick = pkPickResolver != null
            const rowClasses = [
              hoveredPk != null && Math.abs(row.pk - hoveredPk) < 1 ? 'row-hovered' : '',
              addableByRowClick ? 'row-addable' : '',
              pickableByRowClick ? 'row-pickable' : '',
            ]
              .filter(Boolean)
              .join(' ')
            const handleRowAdd = () => (row.node ? onAssignNode(row.node) : onAddNode(row.pk))
            const handleRowClick = pickableByRowClick
              ? () => resolvePkPick(row.pk)
              : addableByRowClick
                ? handleRowAdd
                : undefined
            return (
              <tr
                key={row.piquetNumber}
                data-pk={row.pk}
                className={rowClasses}
                onMouseEnter={() => setHoveredPk(row.pk)}
                onMouseLeave={() => setHoveredPk(null)}
                onClick={handleRowClick}
                title={pickableByRowClick ? 'Cliquer pour choisir ce PK' : addableByRowClick ? 'Cliquer pour ajouter un nœud à ce piquet' : undefined}
              >
                <td>{row.piquetNumber}</td>
                <td>{hasRealNode ? nodeDisplayLabel(row.node!) + (row.isBis ? ' (bis)' : '') : ''}</td>
                <td>{row.partialDistance.toFixed(1)}</td>
                <td>{row.pk.toFixed(1)}</td>
                <td>{row.x.toFixed(6)}</td>
                <td>{row.y.toFixed(6)}</td>
                <td>{row.z.toFixed(2)}</td>
                <td
                  title={(crossingsByRowPk.get(row.pk) ?? []).map((c) => crossingDisplayText(c)).join(', ') || undefined}
                >
                  {(crossingsByRowPk.get(row.pk) ?? []).map((c) => crossingDisplayText(c)).join(', ')}
                </td>
                <td>
                  {(crossingsByRowPk.get(row.pk) ?? [])
                    .map((c) => crossingLength(c, trace?.crossings ?? []))
                    .filter((length): length is number => length != null)
                    .map((length) => `${Math.round(length)} m`)
                    .join(', ')}
                </td>
                {tableScope.kind === 'troncon' && (
                  <>
                    <td>{materialLabel}</td>
                    <td>{segment && pipeCalculated ? pipeDn : '—'}</td>
                    <td>{segment && pipeCalculated ? pipePressureClass?.toUpperCase() : '—'}</td>
                    <td>{segment && pipeCalculated ? pipeDi?.toFixed(1) : '—'}</td>
                    <td>{segment && pipeCalculated ? pipeRoughness?.toFixed(3) : '—'}</td>
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
