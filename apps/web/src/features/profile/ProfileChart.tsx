// Profil en long (cdc §6) — rendu canvas maison : une seule courbe "Terrain" (profil lisse,
// moins bruite que le brut pour representer le terrain), avec curseur de survol synchronise
// (V1-02). Le brut et les points hauts/bas candidats restent calcules cote backend (utiles au
// Lot 3 pour la creation des noeuds brise-charge/vantouses) mais ne sont plus affiches ici.

import { useCallback, useEffect, useState } from 'react'

import { isPlaceholderNode, nodeColor, nodeInitials } from '../../shared/nodeLabels'
import { useAppStore } from '../../state/store'
import type { Node } from '../../shared/types'

const PADDING = { top: 20, right: 24, bottom: 46, left: 70 }
const NODE_MARKER_RADIUS = 9

interface ProfileChartProps {
  showTerrain: boolean
  addNodeMode: boolean
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

export function ProfileChart({ showTerrain, addNodeMode, onAddNode, onEditNode, onAssignNode }: ProfileChartProps) {
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

  const traces = useAppStore((s) => s.traces)
  const nodes = useAppStore((s) => s.nodes)
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
    const zMin = Math.min(...zValues)
    const zMax = Math.max(...zValues)
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
    const drawLine = (points: { pk: number; z: number }[], color: string, lineWidth: number) => {
      ctx.strokeStyle = color
      ctx.lineWidth = lineWidth
      ctx.beginPath()
      points.forEach((p, i) => {
        const x = xScale(p.pk)
        const y = yScale(p.z)
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.stroke()
    }

    if (showTerrain) drawLine(smoothed, '#3ea6ff', 2.5)

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
  }, [canvasEl, profile, hoveredPk, showTerrain, size, traceNodes, pkMin, pkMax])

  const handleMouseMove: React.MouseEventHandler<HTMLCanvasElement> = (event) => {
    if (!profile || profile.raw.length === 0) return
    const canvas = canvasEl
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const x = event.clientX - rect.left
    const plotWidth = rect.width - PADDING.left - PADDING.right
    const pk = pkMin + ((x - PADDING.left) / plotWidth) * (pkMax - pkMin)
    if (pk >= pkMin && pk <= pkMax) setHoveredPk(pk)
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
    <canvas
      ref={canvasCallbackRef}
      className="profile-chart"
      style={{ cursor: addNodeMode ? 'crosshair' : 'default' }}
      onMouseMove={handleMouseMove}
      onMouseLeave={() => setHoveredPk(null)}
      onClick={handleClick}
    />
  )
}
