// Profil en long (cdc §6) — rendu canvas maison : une seule courbe "Terrain" (profil lisse,
// moins bruite que le brut pour representer le terrain), avec curseur de survol synchronise
// (V1-02). Le brut et les points hauts/bas candidats restent calcules cote backend (utiles au
// Lot 3 pour la creation des noeuds brise-charge/vantouses) mais ne sont plus affiches ici.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { isPlaceholderNode, nodeColor, nodeInitials } from '../../shared/nodeLabels'
import { useAppStore } from '../../state/store'
import type { Node, PipeCatalogRow, Segment } from '../../shared/types'

const PADDING = { top: 20, right: 24, bottom: 46, left: 70 }
const NODE_MARKER_RADIUS = 9
const TERRAIN_LINE_COLOR = '#3ea6ff'
const PIEZO_LINE_COLOR = '#f472b6'
const PMS_LINE_COLOR = '#f59e0b'
const HYDROSTATIC_MAX_COLOR = '#22d3ee'
const HYDROSTATIC_MIN_COLOR = '#0e7490'
const CROSSING_COLOR = '#eab308'
// Vitesse (panneau d'info, bouton i) — pas de courbe associee sur le graphique, une couleur propre
// suffit (evite de la confondre avec la pression hydrodynamique, meme si les deux viennent du
// meme calcul).
const VELOCITY_COLOR = '#4ade80'
const GUITAR_BAND_HEIGHT = 28

// Repere court par nature de traversee (consigne utilisateur : routes/pistes, voies ferrees,
// canaux/rivieres/chaabas, bâtiments) — affiche au sommet du repere vertical sur le profil.
const CROSSING_LABELS: Record<string, string> = {
  highway: 'R',
  railway: 'F',
  waterway: 'E',
  building: 'B',
  urban: 'U',
  forest: 'V',
}

// Couleurs des courbes, exportees pour que la legende (ProfileTableView, cases a cocher) affiche
// une pastille de la meme couleur que le trait qu'elle controle (consigne utilisateur) — une
// seule source de verite, jamais une couleur dupliquee/desynchronisee entre les deux fichiers.
export const CURVE_COLORS = {
  terrain: TERRAIN_LINE_COLOR,
  piezo: PIEZO_LINE_COLOR,
  pms: PMS_LINE_COLOR,
  hydrostaticMax: HYDROSTATIC_MAX_COLOR,
  hydrostaticMin: HYDROSTATIC_MIN_COLOR,
  crossing: CROSSING_COLOR,
} as const
// Petite palette fixe pour distinguer les materiaux dans la bande de caracteristiques ("guitare",
// consigne utilisateur) — couleurs volontairement sourdes pour ne pas rivaliser avec les courbes.
// DEUX teintes par materiau (consigne utilisateur : "au moins 2 couleurs a interchanger pour voir
// les nuances") — alternees par bande consecutive (index pair/impair), pas par materiau seul : deux
// paliers de DN successifs du MEME materiau (telescopage) restaient sinon visuellement indistincts.
const MATERIAL_BAND_COLORS: Record<string, [string, string]> = {
  PVC: ['#2d4a63', '#3e6486'],
  PEHD: ['#2d5a4a', '#3e7a64'],
  FD: ['#5a3d2d', '#7a533e'],
  PRV: ['#4a2d5a', '#64407a'],
  ACIER: ['#5a4a2d', '#7a653e'],
}
const DEFAULT_MATERIAL_BAND_COLORS: [string, string] = ['#33415c', '#455a7c']
// Largeur estimee du panneau d'info (bouton i, consigne utilisateur) — au-dela de cette distance
// du bord droit, le curseur le ferait sortir de l'ecran : on le rebascule a gauche du curseur, et
// il revient a droite des que la place suffit de nouveau (recalcule a chaque survol, jamais figé).
const HOVER_INFO_FLIP_MARGIN_PX = 260

interface ProfileChartProps {
  showTerrain: boolean
  showPiezo: boolean
  showPms: boolean
  showHydrostaticMax: boolean
  showHydrostaticMin: boolean
  showCrossings: boolean
  pipeCatalog: PipeCatalogRow[]
  addNodeMode: boolean
  // Bouton d'info deplace dans la barre d'outils (consigne utilisateur, a droite de "+ Nœud") —
  // controle depuis le parent plutot que par un etat/bouton internes a ce composant.
  infoMode: boolean
  // Zoom manuel (consigne utilisateur : "prevoir la possibilite de zoomer... et un bouton de
  // reinitialisation") — pilote a la molette ici, mais l'etat vit dans le parent pour exposer le
  // bouton de reinitialisation dans la barre d'outils, a cote du bouton d'info. `null` = pas de
  // zoom manuel, la plage affichee reste celle deduite de tableScope (trace entiere/troncon).
  zoomRange: { min: number; max: number } | null
  onZoomChange: (range: { min: number; max: number } | null) => void
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

// Vitesse (m/s) du segment couvrant le pk donne — `null` si hors de tout segment ou si ce segment
// n'a pas encore ete calcule (consigne utilisateur : afficher la vitesse dans le panneau d'info,
// bouton i). Une seule valeur par segment (pas une courbe continue), contrairement aux pressions.
function segmentVelocityAtPk(segments: Segment[], pk: number): number | null {
  const seg = segments.find((s) => pk >= s.pk_start - 1e-6 && pk <= s.pk_end + 1e-6)
  if (!seg) return null
  // Le detail PAR PIQUET (glossaire Piquet/Segment/Troncon) prime quand il est disponible — un
  // troncon peut telescoper le DN (donc la vitesse) vers l'aval.
  const details = seg.segment_details
  if (details && details.length > 0) {
    const detail = details.find((d) => d.pk >= pk - 1e-6) ?? details[details.length - 1]
    return detail.velocity ?? null
  }
  return seg.velocity ?? null
}

// Meme interpolation, mais sur un ENSEMBLE de segments disjoints (piezoSegments, ou une des deux
// lignes hydrostatiques) — trouve celui qui couvre le pk demande, `null` si aucun (pas encore
// calcule a cet endroit, ou troncon non gravitaire pour les lignes hydrostatiques). Sert au
// panneau d'info (bouton i, consigne utilisateur) pour afficher les cotes sous le curseur.
function valueAtPkFromLines(lines: { pk: number; z: number }[][], pk: number): number | null {
  for (const line of lines) {
    if (line.length === 0) continue
    const first = line[0]
    const last = line[line.length - 1]
    if (pk >= first.pk - 1e-6 && pk <= last.pk + 1e-6) return interpolateZAtPk(line, pk)
  }
  return null
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
  showCrossings,
  pipeCatalog,
  addNodeMode,
  infoMode,
  zoomRange,
  onZoomChange,
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
  // Une ligne par info (consigne utilisateur : "empilées sur la verticale", chacune coloree comme
  // la courbe dont elle provient — le PK reste blanc, cf. rendu plus bas).
  const [hoverInfo, setHoverInfo] = useState<{
    x: number
    y: number
    lines: { text: string; color: string }[]
    containerWidth: number
  } | null>(null)
  // Pan au clic droit (cf. l'effet plus bas) — sur des refs, pas du state : suivies a chaque
  // frame pendant un drag, un `useState` y redeclencherait un rendu (donc l'effet lui-meme) a
  // chaque pixel, ce qui est exactement le souci de saccades qu'on evite par ailleurs (curseur).
  const panOriginRef = useRef<{ clientX: number; pkMin: number; pkMax: number } | null>(null)
  const pendingPanFrameRef = useRef<number | null>(null)
  const pendingHoverFrameRef = useRef<number | null>(null)
  useEffect(
    () => () => {
      if (pendingHoverFrameRef.current != null) cancelAnimationFrame(pendingHoverFrameRef.current)
      if (pendingPanFrameRef.current != null) cancelAnimationFrame(pendingPanFrameRef.current)
    },
    [],
  )

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
  const baselinePkMin = tableScope.kind === 'troncon' ? Math.max(0, tableScope.pkStart) : 0
  const baselinePkMax = tableScope.kind === 'troncon' ? Math.min(rawPkMax, tableScope.pkEnd) : rawPkMax
  // Le zoom manuel (molette, cf. handleWheel plus bas) affine la plage deduite de tableScope sans
  // jamais en sortir — changer de troncon selectionne redefinit donc naturellement la fenetre
  // zoomable (le parent reinitialise aussi `zoomRange` a ce moment, cf. ProfileTableView).
  const pkMin = zoomRange ? Math.max(baselinePkMin, zoomRange.min) : baselinePkMin
  const pkMax = zoomRange ? Math.min(baselinePkMax, zoomRange.max) : baselinePkMax

  // Ligne(s) piezometrique(s) (consigne utilisateur) : un point par noeud calcule (cote piezo
  // deja resolue par le moteur hydraulique, cf. Node.piezo_head), coupee en plusieurs segments —
  // un par troncon effectivement calcule — des qu'un noeud intermediaire n'a pas encore de valeur
  // (troncon suivant pas/plus calcule, cf. reinitialisation sur modification des donnees). Les
  // noeuds REELS sont rares le long d'un tronçon (souvent seulement les deux extremites) : un zoom
  // manuel etroit peut n'en laisser aucun dans [pkMin, pkMax], ce qui viderait la ligne entiere si
  // on filtrait avant de construire les segments (bug corrige ici, consigne utilisateur). On
  // construit donc chaque segment sur sa plage COMPLETE d'abord, puis on le coupe a la fenetre
  // affichee (meme principe que clipToPkRange pour le terrain).
  // Le DN n'est plus forcement constant entre deux noeuds reels (tableau par piquet, glossaire
  // Piquet/Segment/Troncon — telescopage) : une simple droite entre les deux noeuds reels sous/
  // sur-estime alors la cote piezometrique en cours de route (constate concretement : ligne
  // affichee ~155 m la ou la vraie cote, reconstruite piquet par piquet, est ~177 m). On injecte
  // donc un point par entree de `segment_details`, reconstruit a partir de la cote DEJA CONNUE du
  // noeud reel aval et de la perte de charge cumulee relative de chaque piquet — aucune nouvelle
  // donnee moteur necessaire, tout est deja expose par l'API.
  const piezoSegments = useMemo(() => {
    const sorted = [...traceNodes].sort((a, b) => a.pk - b.pk)
    const full: { pk: number; z: number }[][] = []
    let current: { pk: number; z: number }[] = []
    for (let i = 0; i < sorted.length; i++) {
      const node = sorted[i]
      if (node.piezo_head == null) {
        if (current.length > 1) full.push(current)
        current = []
        continue
      }
      current.push({ pk: node.pk, z: node.piezo_head })
      const next = sorted[i + 1]
      if (next && next.piezo_head != null) {
        const seg = segments.find((s) => s.upstream_node_id === node.id && s.downstream_node_id === next.id)
        const details = seg?.segment_details
        if (details && details.length > 1) {
          const lastCumulative = details[details.length - 1].head_loss_cumulative
          if (lastCumulative != null) {
            for (let j = 0; j < details.length - 1; j++) {
              const d = details[j]
              if (d.head_loss_cumulative == null) continue
              current.push({ pk: d.pk, z: next.piezo_head + (lastCumulative - d.head_loss_cumulative) })
            }
          }
        }
      }
    }
    if (current.length > 1) full.push(current)
    return full
      .filter((seg) => seg[seg.length - 1].pk > pkMin - 1e-6 && seg[0].pk < pkMax + 1e-6)
      .map((seg) => clipToPkRange(seg, Math.max(pkMin, seg[0].pk), Math.min(pkMax, seg[seg.length - 1].pk)))
  }, [traceNodes, segments, pkMin, pkMax])

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
    const pms = (material: string, dn: number, pressureClass: string) =>
      pipeCatalog.find((r) => r.material === material && r.dn === dn && r.pressure_class === pressureClass)?.pms
    const spans: { pkStart: number; pkEnd: number; material: string; dn: number; pressureClass: string; pms?: number }[] = []
    for (const s of segments
      .filter((s) => traceNodeIds.has(s.upstream_node_id) && s.velocity != null)
      .slice()
      .sort((a, b) => a.pk_start - b.pk_start)) {
      const details = s.segment_details
      if (!details || details.length === 0) {
        spans.push({
          pkStart: s.pk_start, pkEnd: s.pk_end, material: s.material, dn: s.dn, pressureClass: s.pressure_class,
          pms: pms(s.material, s.dn, s.pressure_class),
        })
        continue
      }
      // Une bande par RUN consecutif de meme (materiau, DN, classe) — le tableau par piquet
      // (glossaire Piquet/Segment/Troncon) peut telescoper le DN vers l'aval ; une bande par
      // piquet serait illisible, on n'en veut qu'une par palier reellement distinct.
      let runStart = s.pk_start
      for (let i = 0; i < details.length; i++) {
        const detail = details[i]
        const next = details[i + 1]
        const sameAsNext =
          next && next.material === detail.material && next.dn === detail.dn && next.pressure_class === detail.pressure_class
        if (!sameAsNext) {
          spans.push({
            pkStart: runStart, pkEnd: detail.pk, material: detail.material, dn: detail.dn, pressureClass: detail.pressure_class,
            pms: pms(detail.material, detail.dn, detail.pressure_class),
          })
          runStart = detail.pk
        }
      }
    }
    return spans
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

  // Zoom a la molette (consigne utilisateur) : centre sur le pk sous le curseur, dans la limite
  // de la plage deduite de tableScope (jamais plus large que ce qui est deja affiche). Ecouteur
  // natif (pas onWheel React, passif par defaut depuis React 17 — preventDefault y serait sans
  // effet et la page defilerait pendant le zoom) attache/detache a chaque changement de plage.
  useEffect(() => {
    const canvas = canvasEl
    if (!canvas) return
    const MIN_ZOOM_SPAN_M = 5
    const handleWheel = (event: WheelEvent) => {
      const rect = canvas.getBoundingClientRect()
      const plotWidth = rect.width - PADDING.left - PADDING.right
      if (plotWidth <= 0) return
      event.preventDefault()
      const x = event.clientX - rect.left
      const pkAtCursor = pkMin + ((x - PADDING.left) / plotWidth) * (pkMax - pkMin)
      // Molette vers le haut/avant = zoom avant (la plage retrecit), vers le bas/arriere = zoom arriere.
      const factor = event.deltaY < 0 ? 0.85 : 1 / 0.85
      let newMin = pkAtCursor - (pkAtCursor - pkMin) * factor
      let newMax = pkAtCursor + (pkMax - pkAtCursor) * factor
      newMin = Math.max(baselinePkMin, newMin)
      newMax = Math.min(baselinePkMax, newMax)
      if (newMax - newMin < MIN_ZOOM_SPAN_M) return
      if (newMin <= baselinePkMin + 1e-6 && newMax >= baselinePkMax - 1e-6) {
        onZoomChange(null)
        return
      }
      onZoomChange({ min: newMin, max: newMax })
    }
    canvas.addEventListener('wheel', handleWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', handleWheel)
  }, [canvasEl, pkMin, pkMax, baselinePkMin, baselinePkMax, onZoomChange])

  // Deplacement (pan) au clic droit maintenu (consigne utilisateur : "se deplacer... en restant
  // appuye sur le bouton droit, principalement lorsqu'on zoome") — le clic droit n'a aucun autre
  // usage ici (pas de menu contextuel sur le profil), reutilisable sans ambiguite. Ecouteurs sur
  // `window` pour mousemove/mouseup (pas seulement le canvas) : un drag rapide sort facilement du
  // canvas en cours de route, le relachement doit quand meme etre detecte. `contextmenu` est
  // desactive sur le canvas pour que le clic droit ne fasse jamais apparaitre le menu du navigateur.
  useEffect(() => {
    const canvas = canvasEl
    if (!canvas) return
    // Sur un `ref` (pas un `let` local a l'effet) : `onZoomChange` pendant le drag fait changer
    // `pkMin`/`pkMax`, qui re-declenche cet effet (ils sont en dependance) — un `let` perdrait
    // l'origine du drag en cours de route a chaque frame, un ref survit au reattachement des
    // ecouteurs.
    const handleContextMenu = (event: MouseEvent) => event.preventDefault()
    const handleMouseDown = (event: MouseEvent) => {
      if (event.button !== 2) return
      event.preventDefault()
      panOriginRef.current = { clientX: event.clientX, pkMin, pkMax }
    }
    const applyPan = (clientX: number) => {
      const origin = panOriginRef.current
      if (!origin) return
      const rect = canvas.getBoundingClientRect()
      const plotWidth = rect.width - PADDING.left - PADDING.right
      if (plotWidth <= 0) return
      const span = origin.pkMax - origin.pkMin
      const deltaPk = -((clientX - origin.clientX) / plotWidth) * span
      let newMin = origin.pkMin + deltaPk
      let newMax = origin.pkMax + deltaPk
      if (newMin < baselinePkMin) {
        newMin = baselinePkMin
        newMax = newMin + span
      }
      if (newMax > baselinePkMax) {
        newMax = baselinePkMax
        newMin = newMax - span
      }
      onZoomChange({ min: newMin, max: newMax })
    }
    const handleWindowMouseMove = (event: MouseEvent) => {
      if (!panOriginRef.current) return
      if (pendingPanFrameRef.current != null) cancelAnimationFrame(pendingPanFrameRef.current)
      const clientX = event.clientX
      pendingPanFrameRef.current = requestAnimationFrame(() => applyPan(clientX))
    }
    const handleWindowMouseUp = (event: MouseEvent) => {
      if (event.button !== 2) return
      panOriginRef.current = null
    }

    canvas.addEventListener('contextmenu', handleContextMenu)
    canvas.addEventListener('mousedown', handleMouseDown)
    window.addEventListener('mousemove', handleWindowMouseMove)
    window.addEventListener('mouseup', handleWindowMouseUp)
    return () => {
      if (pendingPanFrameRef.current != null) cancelAnimationFrame(pendingPanFrameRef.current)
      canvas.removeEventListener('contextmenu', handleContextMenu)
      canvas.removeEventListener('mousedown', handleMouseDown)
      window.removeEventListener('mousemove', handleWindowMouseMove)
      window.removeEventListener('mouseup', handleWindowMouseUp)
    }
  }, [canvasEl, pkMin, pkMax, baselinePkMin, baselinePkMax, onZoomChange])

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

    // ---- Traversées (routes/rail/pistes, canaux/rivières/chaabas, bâtiments, consigne
    // utilisateur) : repère vertical pointillé + repère court par nature en haut du tracé. ----
    if (showCrossings && trace?.crossings) {
      ctx.font = 'bold 9px Arial'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'bottom'
      for (const crossing of trace.crossings) {
        if (crossing.pk < pkMin - 1e-6 || crossing.pk > pkMax + 1e-6) continue
        const x = xScale(crossing.pk)
        ctx.strokeStyle = CROSSING_COLOR
        ctx.lineWidth = 1
        ctx.setLineDash([3, 3])
        ctx.beginPath()
        ctx.moveTo(x, PADDING.top)
        ctx.lineTo(x, height - PADDING.bottom)
        ctx.stroke()
        ctx.setLineDash([])
        ctx.fillStyle = CROSSING_COLOR
        ctx.fillText(CROSSING_LABELS[crossing.kind] ?? '?', x, PADDING.top + 12)
      }
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
    showCrossings,
    trace?.crossings,
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

  // Le curseur "sautait" sur la carte (consigne utilisateur) : chaque pixel de mousemove
  // declenchait setHoveredPk, donc un redessin COMPLET du canvas (effet ci-dessus, tres charge —
  // toutes les courbes + noeuds), plus une mise a jour du marqueur carte dans un composant
  // separe — sur un mouvement rapide, le thread principal n'arrivait pas a suivre et sautait des
  // positions plutot que de les enchainer. On ne retient donc que la DERNIERE position par frame
  // d'affichage (requestAnimationFrame), jamais plus d'une mise a jour d'etat par frame — le
  // navigateur ne peut de toute facon pas peindre plus souvent, inutile de lui en demander plus.
  const handleMouseMove: React.MouseEventHandler<HTMLCanvasElement> = (event) => {
    if (!profile || profile.raw.length === 0) return
    const canvas = canvasEl
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const clientX = event.clientX
    const clientY = event.clientY
    if (pendingHoverFrameRef.current != null) cancelAnimationFrame(pendingHoverFrameRef.current)
    pendingHoverFrameRef.current = requestAnimationFrame(() => {
      const x = clientX - rect.left
      const plotWidth = rect.width - PADDING.left - PADDING.right
      const pk = pkMin + ((x - PADDING.left) / plotWidth) * (pkMax - pkMin)
      if (pk >= pkMin && pk <= pkMax) setHoveredPk(pk)
      if (infoMode && pk >= pkMin && pk <= pkMax) {
        const hitToleranceInPk = (8 / plotWidth) * (pkMax - pkMin)
        const nearNode = traceNodes.find((n) => Math.abs(n.pk - pk) <= hitToleranceInPk && !isPlaceholderNode(n))
        // Un vrai noeud garde son ID (deja connu, pas de calcul) ; un point de terrain quelconque
        // n'a pas d'identifiant propre en base (decision utilisateur) — seulement PK + altitude,
        // interpolee sur le profil "Terrain" deja trace.
        const displayPk = nearNode ? nearNode.pk : pk
        const z = nearNode ? nearNode.z : interpolateZAtPk(profile.raw, pk)
        // Pression hydrodynamique/hydrostatique (consigne utilisateur, "si applicable" — un
        // troncon non encore calcule, ou en refoulement pour les hydrostatiques, n'en affiche
        // simplement pas la ligne) : cote de la courbe correspondante moins l'altitude du
        // terrain a ce PK, memes courbes (deja clippees a la vue) que celles tracees au canvas.
        const piezoZ = valueAtPkFromLines(piezoSegments, displayPk)
        const hydroMaxZ = valueAtPkFromLines(hydrostaticLines.maxLines, displayPk)
        const hydroMinZ = valueAtPkFromLines(hydrostaticLines.minLines, displayPk)
        const velocity = segmentVelocityAtPk(segments, displayPk)
        const lines: { text: string; color: string }[] = [
          { text: `PK ${Math.round(displayPk)} m${nearNode ? ` · id ${nearNode.id}` : ''}`, color: '#ffffff' },
          { text: `Z ${z.toFixed(1)} m`, color: TERRAIN_LINE_COLOR },
        ]
        if (velocity != null) lines.push({ text: `Vitesse ${velocity.toFixed(2)} m/s`, color: VELOCITY_COLOR })
        if (piezoZ != null) lines.push({ text: `Pression hydrodynamique ${(piezoZ - z).toFixed(1)} m`, color: PIEZO_LINE_COLOR })
        if (hydroMaxZ != null) {
          lines.push({ text: `Pression hydrostatique max ${(hydroMaxZ - z).toFixed(1)} m`, color: HYDROSTATIC_MAX_COLOR })
        }
        if (hydroMinZ != null) {
          lines.push({ text: `Pression hydrostatique min ${(hydroMinZ - z).toFixed(1)} m`, color: HYDROSTATIC_MIN_COLOR })
        }
        setHoverInfo({ x, y: clientY - rect.top, lines, containerWidth: rect.width })
      } else if (infoMode) {
        setHoverInfo(null)
      }
    })
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
          {pipeSpans.map((span, index) => {
            const visibleStart = Math.max(span.pkStart, pkMin)
            const visibleEnd = Math.min(span.pkEnd, pkMax)
            if (visibleEnd <= visibleStart) return null
            const left = guitarXScale(visibleStart)
            const width = guitarXScale(visibleEnd) - left
            const lengthKm = (span.pkEnd - span.pkStart) / 1000
            const label = `${span.material} DN${span.dn} ${span.pressureClass} · L=${lengthKm.toFixed(1)} km`
            const shades = MATERIAL_BAND_COLORS[span.material] ?? DEFAULT_MATERIAL_BAND_COLORS
            return (
              <div
                key={span.pkStart}
                className="profile-guitar-segment"
                style={{ left, width, background: shades[index % 2] }}
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
            // Annule toute frame en attente (cf. handleMouseMove) : sans ça, une mise a jour
            // programmee juste avant la sortie du curseur s'appliquerait APRES ces resets et
            // laisserait une position perimee affichee.
            if (pendingHoverFrameRef.current != null) cancelAnimationFrame(pendingHoverFrameRef.current)
            setHoveredPk(null)
            setHoverInfo(null)
          }}
          onClick={handleClick}
        />
        {hoverInfo && (
          <div
            className="profile-hover-tooltip"
            style={
              hoverInfo.x > hoverInfo.containerWidth - HOVER_INFO_FLIP_MARGIN_PX
                ? { right: hoverInfo.containerWidth - hoverInfo.x + 12, top: hoverInfo.y + 12 }
                : { left: hoverInfo.x + 12, top: hoverInfo.y + 12 }
            }
          >
            {hoverInfo.lines.map((line, i) => (
              <div key={i} style={{ color: line.color }}>
                {line.text}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
