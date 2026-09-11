// Profil en long (cdc §6) — rendu canvas maison : une seule courbe "Terrain" (profil lisse,
// moins bruite que le brut pour representer le terrain), avec curseur de survol synchronise
// (V1-02). Le brut et les points hauts/bas candidats restent calcules cote backend (utiles au
// Lot 3 pour la creation des noeuds brise-charge/vantouses) mais ne sont plus affiches ici.

import { useCallback, useEffect, useMemo, useState } from 'react'

import { isPlaceholderNode, nodeColor, nodeInitials } from '../../shared/nodeLabels'
import { useAppStore } from '../../state/store'
import type { Node, PipeCatalogRow } from '../../shared/types'

const PADDING = { top: 20, right: 24, bottom: 46, left: 70 }
const NODE_MARKER_RADIUS = 9
const TERRAIN_LINE_COLOR = '#3ea6ff'
const PIEZO_LINE_COLOR = '#f472b6'
const PMS_LINE_COLOR = '#f59e0b'
const HYDROSTATIC_MAX_COLOR = '#22d3ee'
const HYDROSTATIC_MIN_COLOR = '#0e7490'
const GUITAR_BAND_HEIGHT = 28

// Couleurs des courbes, exportees pour que la legende (ProfileTableView, cases a cocher) affiche
// une pastille de la meme couleur que le trait qu'elle controle (consigne utilisateur) — une
// seule source de verite, jamais une couleur dupliquee/desynchronisee entre les deux fichiers.
export const CURVE_COLORS = {
  terrain: TERRAIN_LINE_COLOR,
  piezo: PIEZO_LINE_COLOR,
  pms: PMS_LINE_COLOR,
  hydrostaticMax: HYDROSTATIC_MAX_COLOR,
  hydrostaticMin: HYDROSTATIC_MIN_COLOR,
} as const
// Petite palette fixe pour distinguer les materiaux dans la bande de caracteristiques ("guitare",
// consigne utilisateur) — couleurs volontairement sourdes pour ne pas rivaliser avec les courbes.
const MATERIAL_BAND_COLORS: Record<string, string> = {
  PVC: '#2d4a63',
  PEHD: '#2d5a4a',
  FD: '#5a3d2d',
  PRV: '#4a2d5a',
  ACIER: '#5a4a2d',
}
const DEFAULT_MATERIAL_BAND_COLOR = '#33415c'

interface ProfileChartProps {
  showTerrain: boolean
  showPiezo: boolean
  showPms: boolean
  showHydrostaticMax: boolean
  showHydrostaticMin: boolean
  pipeCatalog: PipeCatalogRow[]
  addNodeMode: boolean
  // Bouton d'info deplace dans la barre d'outils (consigne utilisateur, a droite de "+ Nœud") —
  // controle depuis le parent plutot que par un etat/bouton internes a ce composant.
  infoMode: boolean
  onAddNode: (pk: number) => void
  onEditNode: (node: Node) => void
  onAssignNode: (node: Node) => void
}

// Interpolation lineaire de l'altitude au pk donne dans une sequence triee — pour placer le
// marqueur d'un noeud sur la courbe "Terrain" (profil lisse) meme si son pk ne tombe pas
// exactement sur un point echantillonne.
function interpolateZAtPk(points: { pk: number; z: number }[], pk: number): number {
  if (points.length === 0) return 0
  if (pk <= points[0].pk) return points[0].z
  if (pk >= points[points.length - 1].pk) return points[points.length - 1].z
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i]
    const b = points[i + 1]
    if (pk >= a.pk && pk <= b.pk) {
      const t = b.pk === a.pk ? 0 : (pk - a.pk) / (b.pk - a.pk)
      return a.z + t * (b.z - a.z)
    }
  }
  return points[points.length - 1].z
}

// Restreint une courbe a [pkMin, pkMax] (cliquer un troncon dans l'arborescence doit "afficher le
// profil correspondant", consigne utilisateur) — les deux bornes sont interpolees pour que la
// courbe reste continue meme si aucun point echantillonne ne tombe exactement dessus.
function clipToPkRange(points: { pk: number; z: number }[], pkMin: number, pkMax: number): { pk: number; z: number }[] {
  if (points.length === 0) return points
  const inner = points.filter((p) => p.pk > pkMin && p.pk < pkMax)
  return [{ pk: pkMin, z: interpolateZAtPk(points, pkMin) }, ...inner, { pk: pkMax, z: interpolateZAtPk(points, pkMax) }]
}

// Pas "rond" (1/2/2.5/5/10 x 10^n) pour des graduations lisibles, quelle que soit l'amplitude —
// meme principe que les axes de la page de reference fournie par l'utilisateur.
function niceStep(range: number, targetDivisions: number): number {
  if (!Number.isFinite(range) || range <= 0) return 1
  const raw = range / targetDivisions
  const exponent = Math.floor(Math.log10(raw))
  const base = 10 ** exponent
  const normalized = raw / base
  const factor = [1, 2, 2.5, 5, 10].find((f) => normalized <= f) ?? 10
  return factor * base
}

export function ProfileChart({
  showTerrain,
  showPiezo,
  showPms,
  showHydrostaticMax,
  showHydrostaticMin,
  pipeCatalog,
  addNodeMode,
  infoMode,
  onAddNode,
  onEditNode,
  onAssignNode,
}: ProfileChartProps) {
  // Callback ref plutot que useRef+useEffect([]) : le composant retourne "Aucune trace
  // selectionnee"/"Profil non disponible" (pas de <canvas> du tout) tant qu'aucun profil n'existe
  // — donc au tout premier montage (juste apres creation du projet, sans trace), canvasRef.current
  // valait null et un effet a deps [] ne retente jamais une fois le <canvas> reellement rendu plus
  // tard. La callback ref se redeclenche a CHAQUE (dis/re)apparition reelle du noeud DOM, y compris
  // le tout premier affichage en "Profil seul" une fois une trace importee — c'est exactement le
  // bug rapporte (graphe fige/vide au premier affichage).
  const [canvasEl, setCanvasEl] = useState<HTMLCanvasElement | null>(null)
  const canvasCallbackRef = useCallback((node: HTMLCanvasElement | null) => setCanvasEl(node), [])
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [hoverInfo, setHoverInfo] = useState<{ x: number; y: number; text: string } | null>(null)

  const traces = useAppStore((s) => s.traces)
  const nodes = useAppStore((s) => s.nodes)
  const segments = useAppStore((s) => s.segments)
  const selectedTraceId = useAppStore((s) => s.selection.selectedTraceId)
  const tableScope = useAppStore((s) => s.selection.tableScope)
  const hoveredPk = useAppStore((s) => s.selection.hoveredPk)
  const setHoveredPk = useAppStore((s) => s.setHoveredPk)

  const trace = traces.find((t) => t.id === selectedTraceId) ?? traces[0]
  const profile = trace?.elevation_profile
  const traceNodes = trace ? nodes.filter((n) => n.trace_id === trace.id) : []
  // Un troncon selectionne dans l'arborescence "zoome" le profil sur sa plage de PK plutot que de
  // toujours montrer le trace entier — consigne utilisateur ("cliquer sur un troncon... afficher le
  // profil correspondant"), meme logique que le filtrage deja applique a la table (Mode Data).
  const rawPkMax = profile && profile.raw.length > 0 ? Math.max(...profile.raw.map((p) => p.pk)) || 1 : 1
  const pkMin = tableScope.kind === 'troncon' ? Math.max(0, tableScope.pkStart) : 0
  const pkMax = tableScope.kind === 'troncon' ? Math.min(rawPkMax, tableScope.pkEnd) : rawPkMax

  // Ligne(s) piezometrique(s) (consigne utilisateur) : un point par noeud calcule (cote piezo
  // deja resolue par le moteur hydraulique, cf. Node.piezo_head), coupee en plusieurs segments —
  // un par troncon effectivement calcule — des qu'un noeud intermediaire n'a pas encore de valeur
  // (troncon suivant pas/plus calcule, cf. reinitialisation sur modification des donnees).
  const piezoSegments = useMemo(() => {
    const sorted = [...traceNodes].sort((a, b) => a.pk - b.pk)
    const result: { pk: number; z: number }[][] = []
    let current: { pk: number; z: number }[] = []
    for (const node of sorted) {
      if (node.pk < pkMin - 1e-6 || node.pk > pkMax + 1e-6) continue
      if (node.piezo_head != null) {
        current.push({ pk: node.pk, z: node.piezo_head })
      } else {
        if (current.length > 1) result.push(current)
        current = []
      }
    }
    if (current.length > 1) result.push(current)
    return result
  }, [traceNodes, pkMin, pkMax])

  // Caracteristiques de conduite par tronçon de la trace courante (consigne utilisateur : les
  // representer dans le profil, avec leurs changements eventuels) — un "span" par segment reel
  // (materiau/DN/classe), triés le long du PK. Le PMS (mCE) est resolu via le catalogue
  // (Base de données > Conduites) : deja converti depuis le PN (bar) a la saisie du catalogue,
  // aucune conversion a refaire ici. `velocity != null` est LE signal fiable "ce segment a ete
  // calcule avec succes et n'a pas ete modifie depuis" (meme convention que DataTable.tsx) — tant
  // qu'aucun calcul n'a abouti (ou apres une modification qui l'a invalide), ce tableau reste vide
  // et la bande/l'enveloppe PMS restent invisibles (consigne utilisateur : "ne pas les afficher
  // avant le calcul, les enlever apres modification").
  const pipeSpans = useMemo(() => {
    const traceNodeIds = new Set(traceNodes.map((n) => n.id))
    return segments
      .filter((s) => traceNodeIds.has(s.upstream_node_id) && s.velocity != null)
      .slice()
      .sort((a, b) => a.pk_start - b.pk_start)
      .map((s) => ({
        pkStart: s.pk_start,
        pkEnd: s.pk_end,
        material: s.material,
        dn: s.dn,
        pressureClass: s.pressure_class,
        pms: pipeCatalog.find((r) => r.material === s.material && r.dn === s.dn && r.pressure_class === s.pressure_class)?.pms,
      }))
  }, [segments, traceNodes, pipeCatalog])

  const pmsEnvelope = useMemo(() => {
    if (pipeSpans.length === 0) return []
    const base = clipToPkRange(profile?.smoothed ?? [], pkMin, pkMax)
    return base
      .map((p) => {
        const span = pipeSpans.find((sp) => p.pk >= sp.pkStart - 1e-6 && p.pk <= sp.pkEnd + 1e-6)
        if (!span || span.pms == null) return null
        return { pk: p.pk, z: p.z + span.pms }
      })
      .filter((p): p is { pk: number; z: number } => p != null)
  }, [profile, pipeSpans, pkMin, pkMax])

  // Lignes hydrostatiques min/max des tronçons gravitaires (consigne utilisateur) : cotes
  // CONSTANTES (le reservoir amont ne varie pas le long du tronçon), portees par
  // Segment.upstream_water_level_max/min — deja saisies "Modifier le tronçon" (regime gravitaire
  // uniquement, cf. TronconDialog). Un segment de refoulement n'a jamais ces champs renseignes,
  // donc le simple filtre sur leur presence suffit a restreindre l'affichage au gravitaire, sans
  // avoir besoin de re-deriver le regime ici. Comme pour `pipeSpans`, on n'affiche ces lignes
  // qu'une fois un calcul reussi (`velocity != null`, consigne utilisateur — meme si elles ne
  // dependent techniquement que d'une saisie, pas du moteur).
  const hydrostaticLines = useMemo(() => {
    const traceNodeIds = new Set(traceNodes.map((n) => n.id))
    const maxLines: { pk: number; z: number }[][] = []
    const minLines: { pk: number; z: number }[][] = []
    for (const s of segments) {
      if (!traceNodeIds.has(s.upstream_node_id) || s.velocity == null) continue
      const visibleStart = Math.max(s.pk_start, pkMin)
      const visibleEnd = Math.min(s.pk_end, pkMax)
      if (visibleEnd <= visibleStart) continue
      if (s.upstream_water_level_max != null) {
        maxLines.push([{ pk: visibleStart, z: s.upstream_water_level_max }, { pk: visibleEnd, z: s.upstream_water_level_max }])
      }
      if (s.upstream_water_level_min != null) {
        minLines.push([{ pk: visibleStart, z: s.upstream_water_level_min }, { pk: visibleEnd, z: s.upstream_water_level_min }])
      }
    }
    return { maxLines, minLines }
  }, [segments, traceNodes, pkMin, pkMax])

  useEffect(() => {
    if (!canvasEl) return
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      const { width, height } = entry.contentRect
      setSize({ width, height })
    })
    observer.observe(canvasEl)
    return () => observer.disconnect()
  }, [canvasEl])

  useEffect(() => {
    const canvas = canvasEl
    if (!canvas || !profile || profile.raw.length === 0) return
    if (size.width < 10 || size.height < 10) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const { width, height } = size
    canvas.width = width * devicePixelRatio
    canvas.height = height * devicePixelRatio
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.scale(devicePixelRatio, devicePixelRatio)
    ctx.clearRect(0, 0, width, height)

    const smoothed = clipToPkRange(profile.smoothed, pkMin, pkMax)
    const zValues = clipToPkRange(profile.raw, pkMin, pkMax).map((p) => p.z)
    // La ligne piezometrique peut depasser tres largement l'amplitude du terrain (reservoir en
    // altitude, HMT de refoulement...) — l'echelle de l'axe doit l'englober pour ne pas la
    // couper, sinon uniquement quand elle est effectivement affichee.
    const piezoZValues = showPiezo ? piezoSegments.flat().map((p) => p.z) : []
    const pmsZValues = showPms ? pmsEnvelope.map((p) => p.z) : []
    const hydrostaticZValues = [
      ...(showHydrostaticMax ? hydrostaticLines.maxLines.flat() : []),
      ...(showHydrostaticMin ? hydrostaticLines.minLines.flat() : []),
    ].map((p) => p.z)
    const zMin = Math.min(...zValues, ...piezoZValues, ...pmsZValues, ...hydrostaticZValues)
    const zMax = Math.max(...zValues, ...piezoZValues, ...pmsZValues, ...hydrostaticZValues)
    const zPad = Math.max((zMax - zMin) * 0.1, 1)
    const zAxisMin = zMin - zPad
    const zAxisMax = zMax + zPad

    const plotWidth = width - PADDING.left - PADDING.right
    const plotHeight = height - PADDING.top - PADDING.bottom
    const pkSpan = pkMax - pkMin || 1

    const xScale = (pk: number) => PADDING.left + ((pk - pkMin) / pkSpan) * plotWidth
    const yScale = (z: number) => PADDING.top + plotHeight - ((z - zAxisMin) / (zAxisMax - zAxisMin)) * plotHeight

    // ---- Grille + graduations ----
    const xStep = niceStep(pkSpan, 8)
    const yStep = niceStep(zAxisMax - zAxisMin, 5)

    ctx.font = '10px Arial'
    ctx.fillStyle = '#7d8cad'

    ctx.strokeStyle = 'rgba(255,255,255,0.06)'
    ctx.lineWidth = 1
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    for (let z = Math.ceil(zAxisMin / yStep) * yStep; z <= zAxisMax; z += yStep) {
      const y = yScale(z)
      ctx.beginPath()
      ctx.moveTo(PADDING.left, y)
      ctx.lineTo(width - PADDING.right, y)
      ctx.stroke()
      ctx.fillText(`${Math.round(z)}`, PADDING.left - 8, y)
    }

    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    for (let pk = pkMin; pk <= pkMax; pk += xStep) {
      const x = xScale(pk)
      ctx.strokeStyle = 'rgba(255,255,255,0.06)'
      ctx.beginPath()
      ctx.moveTo(x, PADDING.top)
      ctx.lineTo(x, height - PADDING.bottom)
      ctx.stroke()
      ctx.fillText(`${Math.round(pk)}`, x, height - PADDING.bottom + 6)
    }

    // ---- Axes (traits pleins) ----
    ctx.strokeStyle = 'rgba(255,255,255,0.35)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(PADDING.left, PADDING.top)
    ctx.lineTo(PADDING.left, height - PADDING.bottom)
    ctx.lineTo(width - PADDING.right, height - PADDING.bottom)
    ctx.stroke()

    // ---- Titres d'axes ----
    ctx.fillStyle = '#9fb0d1'
    ctx.font = '12px Arial'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'alphabetic'
    ctx.fillText('Distance (m)', PADDING.left + plotWidth / 2, height - 6)

    ctx.save()
    ctx.translate(14, PADDING.top + plotHeight / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.textAlign = 'center'
    ctx.fillText('Altitude (m)', 0, 0)
    ctx.restore()

    // ---- Courbes ----
    const drawLine = (points: { pk: number; z: number }[], color: string, lineWidth: number, dash: number[] = []) => {
      ctx.strokeStyle = color
      ctx.lineWidth = lineWidth
      ctx.setLineDash(dash)
      ctx.beginPath()
      points.forEach((p, i) => {
        const x = xScale(p.pk)
        const y = yScale(p.z)
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.stroke()
      ctx.setLineDash([])
    }

    if (showTerrain) drawLine(smoothed, TERRAIN_LINE_COLOR, 2.5)
    if (showPiezo) {
      for (const segment of piezoSegments) drawLine(segment, PIEZO_LINE_COLOR, 2)
    }
    // Enveloppe PMS en pointilles (consigne utilisateur) — la distingue visuellement des courbes
    // pleines (terrain/piezo/hydrostatiques), utile car elle peut presenter des sauts nets aux
    // changements de conduite.
    if (showPms && pmsEnvelope.length > 1) drawLine(pmsEnvelope, PMS_LINE_COLOR, 1.5, [6, 4])
    if (showHydrostaticMax) {
      for (const line of hydrostaticLines.maxLines) drawLine(line, HYDROSTATIC_MAX_COLOR, 1.5)
    }
    if (showHydrostaticMin) {
      for (const line of hydrostaticLines.minLines) drawLine(line, HYDROSTATIC_MIN_COLOR, 1.5)
    }

    // ---- Noeuds : badge colore + initiales par type (cf. shared/nodeLabels.ts) ----
    // Une extremite pas encore affectee (placeholder "junction") ne doit afficher aucun badge —
    // consigne utilisateur (elle reste cliquable via la detection ci-dessous, juste invisible). Un
    // noeud hors de la plage PK affichee (troncon zoome) est egalement omis.
    for (const node of traceNodes.filter((n) => !isPlaceholderNode(n) && n.pk >= pkMin - 1e-6 && n.pk <= pkMax + 1e-6)) {
      const x = xScale(node.pk)
      const y = yScale(interpolateZAtPk(smoothed, node.pk))
      ctx.beginPath()
      ctx.arc(x, y, NODE_MARKER_RADIUS, 0, Math.PI * 2)
      ctx.fillStyle = nodeColor(node)
      ctx.fill()
      ctx.strokeStyle = '#0c1524'
      ctx.lineWidth = 1.5
      ctx.stroke()
      ctx.fillStyle = '#0c1524'
      ctx.font = 'bold 9px Arial'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(nodeInitials(node), x, y + 0.5)
    }

    if (hoveredPk != null) {
      const x = xScale(hoveredPk)
      ctx.strokeStyle = '#ffd166'
      ctx.lineWidth = 1
      ctx.setLineDash([6, 6])
      ctx.beginPath()
      ctx.moveTo(x, PADDING.top)
      ctx.lineTo(x, height - PADDING.bottom)
      ctx.stroke()
      ctx.setLineDash([])
    }
  }, [
    canvasEl,
    profile,
    hoveredPk,
    showTerrain,
    showPiezo,
    piezoSegments,
    showPms,
    pmsEnvelope,
    showHydrostaticMax,
    showHydrostaticMin,
    hydrostaticLines,
    size,
    traceNodes,
    pkMin,
    pkMax,
  ])

  // Positions en pixels des tronçons pour la bande de caracteristiques ("guitare", en dessous du
  // graphique) — meme formule que xScale dans l'effet de dessin, mais utilisable hors de cet
  // effet (rendu HTML, pas canvas) puisqu'elle ne depend que de `size.width` deja suivi en etat.
  const guitarXScale = useMemo(() => {
    const plotWidth = Math.max(size.width - PADDING.left - PADDING.right, 0)
    const pkSpan = pkMax - pkMin || 1
    return (pk: number) => PADDING.left + ((pk - pkMin) / pkSpan) * plotWidth
  }, [size.width, pkMin, pkMax])

  const handleMouseMove: React.MouseEventHandler<HTMLCanvasElement> = (event) => {
    if (!profile || profile.raw.length === 0) return
    const canvas = canvasEl
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const x = event.clientX - rect.left
    const plotWidth = rect.width - PADDING.left - PADDING.right
    const pk = pkMin + ((x - PADDING.left) / plotWidth) * (pkMax - pkMin)
    if (pk >= pkMin && pk <= pkMax) setHoveredPk(pk)
    if (infoMode && pk >= pkMin && pk <= pkMax) {
      const hitToleranceInPk = (8 / plotWidth) * (pkMax - pkMin)
      const nearNode = traceNodes.find((n) => Math.abs(n.pk - pk) <= hitToleranceInPk && !isPlaceholderNode(n))
      // Un vrai noeud garde son ID (deja connu, pas de calcul) ; un point de terrain quelconque
      // n'a pas d'identifiant propre en base (decision utilisateur) — seulement PK + altitude,
      // interpolee sur le profil "Terrain" deja trace.
      const text = nearNode
        ? `id ${nearNode.id} · PK ${Math.round(nearNode.pk)} m · Z ${Math.round(nearNode.z)} m`
        : `PK ${Math.round(pk)} m · Z ${interpolateZAtPk(profile.raw, pk).toFixed(1)} m`
      setHoverInfo({ x, y: event.clientY - rect.top, text })
    } else if (infoMode) {
      setHoverInfo(null)
    }
  }

  // Clic sur un marqueur de noeud existant (n'importe quel type, y compris une extremite — cdc §6 :
  // "les extremites... doivent aussi etre eligibles pour positionner des ouvrages") -> edition ;
  // sinon, si le mode "+ Noeud" est actif, ajoute un noeud au pk clique.
  const handleClick: React.MouseEventHandler<HTMLCanvasElement> = (event) => {
    if (!profile || profile.raw.length === 0) return
    const canvas = canvasEl
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const x = event.clientX - rect.left
    const plotWidth = rect.width - PADDING.left - PADDING.right
    const pk = pkMin + ((x - PADDING.left) / plotWidth) * (pkMax - pkMin)
    if (pk < pkMin || pk > pkMax) return

    const hitToleranceInPk = (8 / plotWidth) * (pkMax - pkMin)
    const hitNode = traceNodes.find((n) => Math.abs(n.pk - pk) <= hitToleranceInPk)
    // Un placeholder d'extremite n'affiche aucun badge (ci-dessus) : il ne reagit donc au clic que
    // sous le mode "+ Noeud", exactement comme n'importe quel autre point vide du profil — sinon un
    // clic anodin pres du bord ouvrirait une boite de dialogue sans aucun indice visuel prealable.
    if (hitNode && !isPlaceholderNode(hitNode)) {
      onEditNode(hitNode)
      return
    }
    if (addNodeMode) {
      if (hitNode) onAssignNode(hitNode)
      else onAddNode(pk)
    }
  }

  if (!trace) return <p className="empty-hint">Aucune trace sélectionnée.</p>
  if (!profile || profile.raw.length === 0) {
    return <p className="empty-hint">Profil non disponible pour cette trace.</p>
  }

  return (
    <div className="profile-chart-wrap">
      {/* Bande de caracteristiques de conduite ("guitare", consigne utilisateur) — placee
          au-dessus du graphique, dans le flux normal (pas de chevauchement possible avec le
          bouton d'info, qui a ete deplace dans la barre d'outils). */}
      {pipeSpans.length > 0 && (
        <div className="profile-guitar-band" style={{ height: GUITAR_BAND_HEIGHT }}>
          {pipeSpans.map((span) => {
            const visibleStart = Math.max(span.pkStart, pkMin)
            const visibleEnd = Math.min(span.pkEnd, pkMax)
            if (visibleEnd <= visibleStart) return null
            const left = guitarXScale(visibleStart)
            const width = guitarXScale(visibleEnd) - left
            const lengthKm = (span.pkEnd - span.pkStart) / 1000
            const label = `${span.material} DN${span.dn} ${span.pressureClass} · L=${lengthKm.toFixed(1)} km`
            return (
              <div
                key={span.pkStart}
                className="profile-guitar-segment"
                style={{ left, width, background: MATERIAL_BAND_COLORS[span.material] ?? DEFAULT_MATERIAL_BAND_COLOR }}
                title={label}
              >
                {label}
              </div>
            )
          })}
        </div>
      )}
      <div className="profile-canvas-area">
        <canvas
          ref={canvasCallbackRef}
          className="profile-chart"
          style={{ cursor: addNodeMode ? 'crosshair' : 'default' }}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => {
            setHoveredPk(null)
            setHoverInfo(null)
          }}
          onClick={handleClick}
        />
        {hoverInfo && (
          <div className="profile-hover-tooltip" style={{ left: hoverInfo.x + 12, top: hoverInfo.y + 12 }}>
            {hoverInfo.text}
          </div>
        )}
      </div>
    </div>
  )
}
