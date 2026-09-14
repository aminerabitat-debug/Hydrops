// Carte SIG (cdc §6) — MapLibre GL JS (open-source, cf. docs/architecture/01 §1.3).
// Fond satellite Esri World Imagery, avec repli automatique vers OSM standard en cas d'echec
// repete des tuiles — meme source et meme strategie de resilience que la page de reference
// fournie par l'utilisateur (page_carte_profil_itineraire.html).
// Affiche les traces importees et un marqueur de survol synchronise avec le profil/la table (V1-02).

import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ProgressBar } from '../../app/ProgressBar'
import { api } from '../../shared/apiClient'
import { crossingColor, crossingDisplayText, crossingZoneFillColor, isZoneKind } from '../../shared/crossingColors'
import { buildVertices, coordinatesForPkRange, haversineDistanceM, interpolateLonLatAtPk, nearestPkForPoint } from '../../shared/geo'
import { fetchApproximateLocationFromIp } from '../../shared/ipGeolocation'
import { isPlaceholderNode, nodeColor, nodeDisplayLabel, nodeInitials } from '../../shared/nodeLabels'
import { useAppStore } from '../../state/store'
import type { Crossing, TraceGeometry } from '../../shared/types'
import { CrossingDialog, type CrossingSubmitPayload } from './CrossingDialog'

type TraceFeatureCollection = {
  type: 'FeatureCollection'
  features: Array<{
    type: 'Feature'
    properties: { id: string; selected: boolean }
    geometry: TraceGeometry['geometry']
  }>
}

const SATELLITE_STYLE = {
  version: 8,
  sources: {
    satellite: {
      type: 'raster',
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      ],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    },
  },
  layers: [{ id: 'satellite', type: 'raster', source: 'satellite' }],
} as unknown as maplibregl.StyleSpecification

const STREET_FALLBACK_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
} as unknown as maplibregl.StyleSpecification

const TILE_FAILURE_THRESHOLD = 4

export function MapView() {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const hoverMarkerRef = useRef<maplibregl.Marker | null>(null)
  const nodeMarkersRef = useRef<Map<string, maplibregl.Marker>>(new Map())
  const crossingMarkersRef = useRef<Map<string, maplibregl.Marker>>(new Map())
  const tileFailureCountRef = useRef(0)
  const [usingFallbackBasemap, setUsingFallbackBasemap] = useState(false)
  // Petit bouton d'information (consigne utilisateur) : affiche l'ID et le PK du piquet survole
  // sur la carte — desactive par defaut pour ne pas alourdir la carte en usage courant.
  const [infoMode, setInfoMode] = useState(false)
  const [hoverInfo, setHoverInfo] = useState<{ x: number; y: number; text: string } | null>(null)
  // Detection des traversees (consigne utilisateur : bouton sous le bouton PK de la carte, sur la
  // trace SELECTIONNEE — appel EXPLICITE, jamais automatique, a un service externe (Overpass/OSM)
  // potentiellement lent ou indisponible).
  const [detectingCrossings, setDetectingCrossings] = useState(false)
  // Ajout manuel d'une traversee (consigne utilisateur) — meme paradigme que "+ Nœud" (bascule +
  // clic sur la trace), mais local a la carte (pas d'etat partage avec le profil, aucun besoin ici).
  const [addCrossingMode, setAddCrossingMode] = useState(false)
  const [crossingDialog, setCrossingDialog] = useState<
    | { mode: 'create'; traceId: string; pk: number }
    | { mode: 'edit'; traceId: string; crossing: Crossing }
    | null
  >(null)
  // Mesure de distance (consigne utilisateur) — meme paradigme que les autres modes ci-dessus :
  // bascule + clic sur la carte (n'importe ou, pas restreint a une trace). `measurePoints` en
  // WGS84 [lon, lat], un segment de ligne temporaire relie les points cliques dans l'ordre.
  const [measureMode, setMeasureMode] = useState(false)
  const [measurePoints, setMeasurePoints] = useState<[number, number][]>([])
  const measureMarkersRef = useRef<maplibregl.Marker[]>([])

  const sessionId = useAppStore((s) => s.sessionId)
  const traces = useAppStore((s) => s.traces)
  const nodes = useAppStore((s) => s.nodes)
  const selectedTraceId = useAppStore((s) => s.selection.selectedTraceId)
  const setSelectedTrace = useAppStore((s) => s.setSelectedTrace)
  const hoveredPk = useAppStore((s) => s.selection.hoveredPk)
  const mapFocusRequest = useAppStore((s) => s.mapFocusRequest)
  const showCrossings = useAppStore((s) => s.showCrossings)
  const setShowCrossings = useAppStore((s) => s.setShowCrossings)
  const updateTrace = useAppStore((s) => s.updateTrace)
  const setStatusMessage = useAppStore((s) => s.setStatusMessage)
  const pkPickResolver = useAppStore((s) => s.pkPickResolver)
  const resolvePkPick = useAppStore((s) => s.resolvePkPick)
  const layoutMode = useAppStore((s) => s.layoutMode)
  const requestProfileFocus = useAppStore((s) => s.requestProfileFocus)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: SATELLITE_STYLE,
      center: [2.35, 48.85],
      zoom: 11,
    })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current = map

    // Centrage au demarrage selon l'adresse IP de connexion (consigne utilisateur) — le centre
    // Paris ci-dessus n'est qu'un repli le temps de la resolution (reseau, service de
    // geolocalisation indisponible) ; `jumpTo` (pas `flyTo`) pour un repositionnement instantane,
    // avant que l'utilisateur n'ait eu le temps d'interagir avec la carte. Ne concerne que la vue
    // INITIALE : un projet/trace deja ouvert reprend la main via l'effet mapFocusRequest ci-dessous.
    let cancelled = false
    fetchApproximateLocationFromIp().then((location) => {
      if (cancelled || !location) return
      map.jumpTo({ center: [location.lon, location.lat], zoom: 11 })
    })

    // Bascule vers un fond standard si le fond satellite echoue de facon repetee (reseau,
    // service indisponible) — jamais de carte figee sur des tuiles en erreur.
    map.on('error', (event) => {
      if (!event.error || usingFallbackBasemap) return
      tileFailureCountRef.current += 1
      if (tileFailureCountRef.current >= TILE_FAILURE_THRESHOLD) {
        setUsingFallbackBasemap(true)
      }
    })

    // MapLibre ne redimensionne pas son canvas tout seul quand le conteneur change de taille
    // (bascule Carte/Profil-Table/Vue combinee, glissiere deplacee...) — sans cet observer,
    // la carte reste figee a sa taille d'origine dans un coin du conteneur agrandi.
    const resizeObserver = new ResizeObserver(() => map.resize())
    resizeObserver.observe(containerRef.current)

    return () => {
      cancelled = true
      resizeObserver.disconnect()
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !usingFallbackBasemap) return
    map.setStyle(STREET_FALLBACK_STYLE)
  }, [usingFallbackBasemap])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const applyTraces = () => {
      if (!map.isStyleLoaded()) return
      const data: TraceFeatureCollection = {
        type: 'FeatureCollection',
        features: traces.map((trace) => ({
          type: 'Feature',
          properties: { id: trace.id, selected: trace.id === selectedTraceId },
          geometry: trace.geometry,
        })),
      }

      const source = map.getSource('traces') as maplibregl.GeoJSONSource | undefined
      if (source) {
        source.setData(data as unknown as GeoJSON.FeatureCollection)
      } else {
        map.addSource('traces', { type: 'geojson', data: data as unknown as GeoJSON.FeatureCollection })
        map.addLayer({
          id: 'traces-line',
          type: 'line',
          source: 'traces',
          paint: {
            'line-color': ['case', ['get', 'selected'], '#ffd166', '#3ea6ff'],
            'line-width': ['case', ['get', 'selected'], 5, 3],
          },
        })
        map.on('click', 'traces-line', (event) => {
          const id = event.features?.[0]?.properties?.id as string | undefined
          if (id) setSelectedTrace(id)
        })
      }

      const allCoords = traces.flatMap((t) => t.geometry.coordinates)
      if (allCoords.length > 0) {
        const bounds = allCoords.reduce(
          (b, c) => b.extend(c),
          new maplibregl.LngLatBounds(allCoords[0], allCoords[0]),
        )
        map.fitBounds(bounds, { padding: 40, maxZoom: 15, duration: 300 })
      }
    }

    if (map.isStyleLoaded()) applyTraces()
    else map.once('load', applyTraces)
    // Reappliquer aussi apres un changement de style (bascule vers le fond de repli), qui
    // supprime toutes les sources/couches ajoutees manuellement.
    map.on('styledata', applyTraces)
    return () => {
      map.off('styledata', applyTraces)
    }
    // selectedTraceId volontairement absent des deps : ce n'est plus la simple SELECTION d'un
    // trace qui doit recadrer la carte sur l'ensemble du projet (sinon impossible de zoomer sur un
    // seul trace, cf. l'effet mapFocusRequest ci-dessous qui prend le relais pour la navigation
    // explicite depuis l'arborescence) — seul un changement du JEU de traces (import/suppression)
    // re-cadre automatiquement.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [traces, setSelectedTrace, usingFallbackBasemap])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapFocusRequest) return

    // Recadrage explicite demande depuis l'arborescence (cdc, consigne utilisateur) : projet entier
    // / un trace / un ouvrage (point) / un troncon (sous-plage de PK d'un trace). Pas de garde
    // `isStyleLoaded()` ici (contrairement a l'effet applyTraces ci-dessus, qui lui ajoute des
    // sources/couches et en a reellement besoin) : `fitBounds`/`flyTo` ne font que deplacer la
    // camera, valide des que l'instance Map existe — `isStyleLoaded()` peut renvoyer false de facon
    // intermittente (tuiles en cours de chargement) et l'effet ne se redeclenche pas forcement
    // ensuite, ce qui a deja fait ignorer silencieusement des demandes de recadrage en test. La
    // transition reste animee (duration non nulle) : un saut instantane (duration: 0) s'est avere
    // ne PAS rafraichir les tuiles raster sur un grand ecart de zoom (camera interne correcte via
    // getCenter/getZoom, mais aucune nouvelle requete de tuile, rendu fige) — contrairement a un
    // `fitBounds` anime, qui fonctionne de façon fiable ici.
    const applyFocus = () => {
      const { target } = mapFocusRequest

      if (target.kind === 'project') {
        const allCoords = traces.flatMap((t) => t.geometry.coordinates)
        if (allCoords.length === 0) return
        const bounds = allCoords.reduce(
          (b, c) => b.extend(c),
          new maplibregl.LngLatBounds(allCoords[0], allCoords[0]),
        )
        map.fitBounds(bounds, { padding: 40, maxZoom: 15, duration: 600 })
        return
      }

      if (target.kind === 'trace') {
        const trace = traces.find((t) => t.id === target.traceId)
        if (!trace || trace.geometry.coordinates.length === 0) return
        const coords = trace.geometry.coordinates
        const bounds = coords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]))
        map.fitBounds(bounds, { padding: 40, maxZoom: 16, duration: 600 })
        return
      }

      if (target.kind === 'node') {
        const node = nodes.find((n) => n.id === target.nodeId)
        if (!node) return
        map.flyTo({ center: [node.x, node.y], zoom: Math.max(map.getZoom(), 17), duration: 600 })
        return
      }

      const trace = traces.find((t) => t.id === target.traceId)
      if (!trace) return
      const coords = coordinatesForPkRange(trace.geometry.coordinates as [number, number][], target.pkStart, target.pkEnd)
      if (coords.length === 0) return
      const bounds = coords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]))
      map.fitBounds(bounds, { padding: 60, maxZoom: 18, duration: 600 })
    }

    applyFocus()
  }, [mapFocusRequest, traces, nodes])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !infoMode) {
      setHoverInfo(null)
      return
    }

    const handleMove = (event: maplibregl.MapLayerMouseEvent) => {
      const feature = event.features?.[0]
      const traceId = feature?.properties?.id as string | undefined
      const trace = traces.find((t) => t.id === traceId)
      if (!trace) return
      const vertices = buildVertices(trace.geometry.coordinates as [number, number][])
      const pk = nearestPkForPoint(vertices, event.lngLat.lng, event.lngLat.lat)
      setHoverInfo({ x: event.point.x, y: event.point.y, text: `PK ${Math.round(pk)} m` })
    }
    const handleLeave = () => setHoverInfo(null)

    map.on('mousemove', 'traces-line', handleMove)
    map.on('mouseleave', 'traces-line', handleLeave)
    return () => {
      map.off('mousemove', 'traces-line', handleMove)
      map.off('mouseleave', 'traces-line', handleLeave)
    }
  }, [infoMode, traces])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    // Marqueurs de noeuds — un maplibregl.Marker HTML par noeud (pas une couche GL circle+symbol)
    // pour reutiliser directement la couleur/les initiales par type (shared/nodeLabels.ts) sans
    // dependre d'un serveur de glyphes de police (necessaire pour un text-field GL, absent de nos
    // styles satellite/OSM inline). L'ajout/suppression se fait depuis le profil (ProfileChart) ;
    // la carte les affiche pour la synchro visuelle (V1-02).
    const markers = nodeMarkersRef.current
    const seenIds = new Set<string>()

    // Une extremite pas encore affectee a un ouvrage reel (placeholder "junction") ne doit
    // afficher aucun marqueur — consigne utilisateur, elle doit se comporter comme si aucun noeud
    // n'existait la tant qu'elle n'est pas assignee.
    for (const node of nodes.filter((n) => !isPlaceholderNode(n))) {
      seenIds.add(node.id)
      let marker = markers.get(node.id)
      if (!marker) {
        const el = document.createElement('div')
        el.className = 'map-node-marker'
        marker = new maplibregl.Marker({ element: el }).setLngLat([node.x, node.y]).addTo(map)
        markers.set(node.id, marker)
      } else {
        marker.setLngLat([node.x, node.y])
      }
      const el = marker.getElement()
      el.style.backgroundColor = nodeColor(node)
      el.textContent = nodeInitials(node)
      el.title = infoMode
        ? `${nodeDisplayLabel(node)} · id ${node.id} · PK ${Math.round(node.pk)} m`
        : nodeDisplayLabel(node)
    }

    for (const [id, marker] of markers) {
      if (!seenIds.has(id)) {
        marker.remove()
        markers.delete(id)
      }
    }
  }, [nodes, infoMode])

  // Traversées détectées (consigne utilisateur : afficher/masquer sur la carte ET le profil) —
  // même principe que les marqueurs de nœuds ci-dessus, sur toutes les traces (pas seulement la
  // sélectionnée), affiché/masqué via le même bouton que ProfileChart (état partagé, store.ts).
  // Couleur par sous-catégorie (palette gris/bleu, consigne utilisateur) et clic pour modifier/
  // supprimer — réassignés à CHAQUE rendu (pas seulement à la création du marqueur) pour ne jamais
  // capturer une version périmée de `crossing`/`trace.id` dans la closure du gestionnaire de clic.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const markers = crossingMarkersRef.current
    const seenIds = new Set<string>()
    if (showCrossings) {
      for (const trace of traces) {
        for (const crossing of trace.crossings ?? []) {
          seenIds.add(crossing.id)
          let marker = markers.get(crossing.id)
          if (!marker) {
            const el = document.createElement('div')
            el.className = 'map-crossing-marker'
            marker = new maplibregl.Marker({ element: el }).setLngLat([crossing.lon, crossing.lat]).addTo(map)
            markers.set(crossing.id, marker)
          }
          const el = marker.getElement()
          el.style.backgroundColor = crossingColor(crossing.kind, crossing.subtype)
          el.title = crossingDisplayText(crossing)
          el.onclick = (event) => {
            event.stopPropagation()
            setCrossingDialog({ mode: 'edit', traceId: trace.id, crossing })
          }
        }
      }
    }
    for (const [id, marker] of markers) {
      if (!seenIds.has(id)) {
        marker.remove()
        markers.delete(id)
      }
    }
  }, [traces, showCrossings])

  const hoveredTrace = traces.find((t) => t.id === selectedTraceId) ?? traces[0]
  // Sommets + distance cumulee (haversine) le long de la trace survolee — memorises pour ne pas
  // les reconstruire a chaque frame de survol (cf. shared/geo.ts, meme fonction que
  // nearestPkForPoint ci-dessous, pour une interpolation CONTINUE entre deux sommets plutot que
  // l'ancien arrondi au sommet le plus proche qui faisait "sauter" le curseur carte).
  const hoveredTraceVertices = useMemo(
    () => (hoveredTrace ? buildVertices(hoveredTrace.geometry.coordinates as [number, number][]) : null),
    [hoveredTrace],
  )

  // Consigne utilisateur : le 1er clic DETECTE (appel Overpass) ET affiche ; les clics suivants ne
  // font plus qu'afficher/masquer les traversées déjà connues, sans reinterroger Overpass a
  // chaque fois — `hoveredTrace.crossings == null` distingue "jamais détectées" de "détectées,
  // liste vide" (cf. shared/types.ts). Un resultat VIDE (rien detecte) est traite comme "jamais
  // detectees" pour le comportement du bouton (consigne utilisateur : "si rien n'est detecte, ne
  // pas changer la fonction du bouton a afficher/masquer") — afficher/masquer n'aurait de toute
  // facon rien a montrer, et l'utilisateur doit pouvoir reessayer (ex. apres correction cote OSM)
  // sans que le bouton reste bloque en mode bascule.
  const handleCrossingsButtonClick = async () => {
    if (!hoveredTrace) return
    if (hoveredTrace.crossings != null && hoveredTrace.crossings.length > 0) {
      setShowCrossings(!showCrossings)
      return
    }
    if (!sessionId) return
    setDetectingCrossings(true)
    setStatusMessage('Détection des traversées en cours (Overpass/OpenStreetMap)...')
    try {
      const updated = await api.detectCrossings(sessionId, hoveredTrace.id)
      updateTrace(updated)
      setShowCrossings(true)
      const count = updated.crossings?.length ?? 0
      setStatusMessage(count > 0 ? `${count} traversée(s) détectée(s)` : 'Aucune traversée détectée', 'success')
    } catch (error) {
      setStatusMessage(`Détection des traversées échouée : ${(error as Error).message}`, 'error')
    } finally {
      setDetectingCrossings(false)
    }
  }

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (!hoveredTraceVertices || hoveredPk == null) {
      hoverMarkerRef.current?.remove()
      hoverMarkerRef.current = null
      return
    }
    const point = interpolateLonLatAtPk(hoveredTraceVertices, hoveredPk)
    if (!hoverMarkerRef.current) {
      hoverMarkerRef.current = new maplibregl.Marker({ color: '#ffd166' }).setLngLat(point).addTo(map)
    } else {
      hoverMarkerRef.current.setLngLat(point)
    }
  }, [hoveredPk, hoveredTraceVertices])

  // Ajout manuel d'une traversee (consigne utilisateur) : en mode actif, un clic sur la trace
  // SELECTIONNEE (meme portee que le bouton de detection ci-dessus) ouvre le dialogue de creation
  // au PK clique — jamais sur une autre trace, pour rester coherent avec le reste de la toolbar
  // carte qui n'agit que sur `hoveredTrace`.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !addCrossingMode || !hoveredTrace || !hoveredTraceVertices) return
    const handleClick = (event: maplibregl.MapLayerMouseEvent) => {
      const id = event.features?.[0]?.properties?.id as string | undefined
      if (id !== hoveredTrace.id) return
      const pk = nearestPkForPoint(hoveredTraceVertices, event.lngLat.lng, event.lngLat.lat)
      setCrossingDialog({ mode: 'create', traceId: hoveredTrace.id, pk })
    }
    map.on('click', 'traces-line', handleClick)
    return () => {
      map.off('click', 'traces-line', handleClick)
    }
  }, [addCrossingMode, hoveredTrace, hoveredTraceVertices])

  // Selection de PK depuis la carte (consigne utilisateur : bouton "…" du panneau Contraintes de
  // la fenetre Tronçon) — meme principe que l'ajout de traversee ci-dessus : un clic sur la trace
  // SURVOLEE, pendant qu'une selection est demandee (store, partage avec ProfileChart/DataTable),
  // resout le PK le plus proche au lieu du comportement habituel du clic.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !pkPickResolver || !hoveredTrace || !hoveredTraceVertices) return
    const handleClick = (event: maplibregl.MapLayerMouseEvent) => {
      const id = event.features?.[0]?.properties?.id as string | undefined
      if (id !== hoveredTrace.id) return
      const pk = nearestPkForPoint(hoveredTraceVertices, event.lngLat.lng, event.lngLat.lat)
      resolvePkPick(pk)
    }
    map.on('click', 'traces-line', handleClick)
    return () => {
      map.off('click', 'traces-line', handleClick)
    }
  }, [pkPickResolver, hoveredTrace, hoveredTraceVertices, resolvePkPick])

  // Mesure de distance (consigne utilisateur) : en mode actif, chaque clic sur la carte (n'importe
  // ou, pas restreint a une couche) ajoute un point — pas de couche cible comme addCrossingMode/
  // pkPickResolver ci-dessus, une mesure n'est pas liee a une trace.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !measureMode) return
    const handleClick = (event: maplibregl.MapMouseEvent) => {
      setMeasurePoints((pts) => [...pts, [event.lngLat.lng, event.lngLat.lat]])
    }
    map.on('click', handleClick)
    return () => {
      map.off('click', handleClick)
    }
  }, [measureMode])

  // Distance cumulee (consigne utilisateur) — meme formule haversine que le reste de l'app
  // (shared/geo.ts), sommee entre points consecutifs cliques.
  const measureTotalDistanceM = useMemo(() => {
    let total = 0
    for (let i = 1; i < measurePoints.length; i++) {
      const [lon1, lat1] = measurePoints[i - 1]
      const [lon2, lat2] = measurePoints[i]
      total += haversineDistanceM(lon1, lat1, lon2, lat2)
    }
    return total
  }, [measurePoints])

  // Ligne temporaire reliant les points de mesure (meme patron add-source-ou-setData que le halo
  // de zone de traversee ci-dessous) + marqueurs a chaque point clique.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const applyMeasureLine = () => {
      if (!map.isStyleLoaded()) return
      const data: GeoJSON.FeatureCollection = {
        type: 'FeatureCollection',
        features:
          measurePoints.length >= 2
            ? [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: measurePoints } }]
            : [],
      }
      const source = map.getSource('measure-line') as maplibregl.GeoJSONSource | undefined
      if (source) {
        source.setData(data)
      } else {
        map.addSource('measure-line', { type: 'geojson', data })
        map.addLayer({
          id: 'measure-line-layer',
          type: 'line',
          source: 'measure-line',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#eab308', 'line-width': 2, 'line-dasharray': [2, 2] },
        })
      }
    }
    if (map.isStyleLoaded()) applyMeasureLine()
    else map.once('load', applyMeasureLine)
    map.on('styledata', applyMeasureLine)
    return () => {
      map.off('styledata', applyMeasureLine)
    }
  }, [measurePoints])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    measureMarkersRef.current.forEach((m) => m.remove())
    measureMarkersRef.current = measurePoints.map(([lon, lat]) => {
      const el = document.createElement('div')
      el.className = 'map-measure-marker'
      return new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map)
    })
    return () => {
      measureMarkersRef.current.forEach((m) => m.remove())
      measureMarkersRef.current = []
    }
  }, [measurePoints])

  const handleToggleMeasure = () => {
    setMeasureMode((v) => !v)
    setMeasurePoints([])
  }

  const formatMeasureDistance = (meters: number): string =>
    meters >= 1000 ? `${(meters / 1000).toFixed(2)} km` : `${Math.round(meters)} m`

  // Synchronisation zoom carte -> profil/table (consigne utilisateur : "en Vue combinée, quand un
  // tracé est sélectionné, zoomer sur la carte doit centrer le profil/la table sur les piquets au
  // centre de la carte") — direction inverse de mapFocusRequest, uniquement en Vue combinee et avec
  // un tracé explicitement selectionne (pas de repli sur le premier tracé comme hoveredTrace
  // ci-dessus : ce n'est PAS le meme besoin — ici on ne veut agir que sur une selection explicite).
  useEffect(() => {
    const map = mapRef.current
    if (!map || layoutMode !== 'both' || !selectedTraceId) return
    const trace = traces.find((t) => t.id === selectedTraceId)
    if (!trace) return
    const vertices = buildVertices(trace.geometry.coordinates as [number, number][])
    const handleMoveEnd = () => {
      const bounds = map.getBounds()
      const west = bounds.getWest()
      const east = bounds.getEast()
      const south = bounds.getSouth()
      const north = bounds.getNorth()
      const visible = vertices.filter((v) => v.lon >= west && v.lon <= east && v.lat >= south && v.lat <= north)
      if (visible.length < 2) return
      const pks = visible.map((v) => v.pk)
      requestProfileFocus({ pkStart: Math.min(...pks), pkEnd: Math.max(...pks) })
    }
    map.on('moveend', handleMoveEnd)
    return () => {
      map.off('moveend', handleMoveEnd)
    }
  }, [layoutMode, selectedTraceId, traces, requestProfileFocus])

  // Halo le long du trace pour une traversee de ZONE (urbain/forestier, consigne utilisateur :
  // "une sorte de shadow autour du tracé dans cette zone") — un sous-segment de geometrie par paire
  // Entree/Sortie consecutive de MEME nature, regroupees par kind avant appariement (une trace peut
  // traverser des zones de natures differentes qui se chevauchent/s'entrelacent). Les reperes
  // Entree/Sortie existants restent affiches par-dessus (marqueurs DOM, independants de ce calque).
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const applyHalo = () => {
      if (!map.isStyleLoaded()) return
      const features: GeoJSON.Feature[] = []
      if (showCrossings) {
        for (const trace of traces) {
          const allCrossings = trace.crossings ?? []
          for (const kind of ['urban', 'forest'] as const) {
            const ofKind = allCrossings.filter((c) => c.kind === kind).sort((a, b) => a.pk - b.pk)
            for (let i = 0; i < ofKind.length - 1; i++) {
              const entry = ofKind[i]
              const exit = ofKind[i + 1]
              if (!entry.label?.startsWith('Entrée') || !exit.label?.startsWith('Sortie')) continue
              const coords = coordinatesForPkRange(trace.geometry.coordinates as [number, number][], entry.pk, exit.pk)
              if (coords.length < 2) continue
              features.push({ type: 'Feature', properties: { kind }, geometry: { type: 'LineString', coordinates: coords } })
            }
          }
        }
      }
      const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }
      const source = map.getSource('crossing-zones') as maplibregl.GeoJSONSource | undefined
      if (source) {
        source.setData(data)
      } else {
        map.addSource('crossing-zones', { type: 'geojson', data })
        map.addLayer(
          {
            id: 'crossing-zones-halo',
            type: 'line',
            source: 'crossing-zones',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
              'line-color': ['match', ['get', 'kind'], 'urban', crossingColor('urban'), 'forest', crossingColor('forest'), '#888888'],
              'line-width': 16,
              'line-opacity': 0.3,
            },
          },
          map.getLayer('traces-line') ? 'traces-line' : undefined,
        )
      }
    }
    if (map.isStyleLoaded()) applyHalo()
    else map.once('load', applyHalo)
    map.on('styledata', applyHalo)
    return () => {
      map.off('styledata', applyHalo)
    }
  }, [traces, showCrossings])

  const handleCrossingSubmit = async (payload: CrossingSubmitPayload) => {
    if (!sessionId || !crossingDialog) return
    const updated =
      crossingDialog.mode === 'create'
        ? await api.addCrossing(sessionId, crossingDialog.traceId, payload)
        : await api.updateCrossing(sessionId, crossingDialog.traceId, crossingDialog.crossing.id, payload)
    updateTrace(updated)
    setShowCrossings(true)
    setStatusMessage(crossingDialog.mode === 'create' ? 'Traversée ajoutée' : 'Traversée modifiée', 'success')
  }

  const handleCrossingDelete = async () => {
    if (!sessionId || !crossingDialog || crossingDialog.mode !== 'edit') return
    const updated = await api.deleteCrossing(sessionId, crossingDialog.traceId, crossingDialog.crossing.id)
    updateTrace(updated)
    setStatusMessage('Traversée supprimée', 'success')
  }

  return (
    <div className="map-view-wrap">
      <div ref={containerRef} className={`map-view ${pkPickResolver ? 'map-view--picking' : ''}`} />
      <button
        type="button"
        className={`map-info-toggle ${infoMode ? 'active' : ''}`}
        onClick={() => setInfoMode((v) => !v)}
        title="Afficher l'ID et le PK du piquet survolé"
        aria-label="Afficher l'ID et le PK du piquet survolé"
      >
        PK ?
      </button>
      <button
        type="button"
        className={`map-info-toggle map-crossings-toggle ${(hoveredTrace?.crossings?.length ?? 0) > 0 && showCrossings ? 'active' : ''}`}
        disabled={!hoveredTrace || detectingCrossings}
        onClick={handleCrossingsButtonClick}
        title={
          !hoveredTrace?.crossings || hoveredTrace.crossings.length === 0
            ? "Détecter les traversées (routes, voies ferrées, cours d'eau, zones urbaines/forestières, bâtiments) sur la trace sélectionnée"
            : showCrossings
              ? 'Masquer les traversées'
              : 'Afficher les traversées'
        }
        aria-label="Détecter/afficher les traversées"
      >
        {detectingCrossings ? '⏳' : '🛣️'}
      </button>
      <button
        type="button"
        className={`map-info-toggle map-add-crossing-toggle ${addCrossingMode ? 'active' : ''}`}
        disabled={!hoveredTrace}
        onClick={() => setAddCrossingMode((v) => !v)}
        title="Ajouter une traversée (cliquer ensuite sur la trace)"
        aria-label="Ajouter une traversée"
      >
        📍
      </button>
      <button
        type="button"
        className={`map-info-toggle map-measure-toggle ${measureMode ? 'active' : ''}`}
        onClick={handleToggleMeasure}
        title="Mesurer une distance (cliquer plusieurs points sur la carte)"
        aria-label="Mesurer une distance"
      >
        📏
      </button>
      {measureMode && (
        <div className="map-measure-info">
          <span>Distance : {measurePoints.length >= 2 ? formatMeasureDistance(measureTotalDistanceM) : '—'}</span>
          {measurePoints.length > 0 && (
            <button type="button" className="btn-row-icon" title="Effacer les points" onClick={() => setMeasurePoints([])}>
              ✕
            </button>
          )}
        </div>
      )}
      {detectingCrossings && (
        <div className="map-progress">
          <ProgressBar label="Détection des traversées…" />
        </div>
      )}
      {hoverInfo && (
        <div className="map-hover-tooltip" style={{ left: hoverInfo.x + 12, top: hoverInfo.y + 12 }}>
          {hoverInfo.text}
        </div>
      )}
      {crossingDialog && (
        <CrossingDialog
          mode={crossingDialog.mode}
          initialPk={crossingDialog.mode === 'create' ? crossingDialog.pk : crossingDialog.crossing.pk}
          initialKind={crossingDialog.mode === 'edit' ? crossingDialog.crossing.kind : undefined}
          initialLabel={crossingDialog.mode === 'edit' ? crossingDialog.crossing.label : undefined}
          onClose={() => setCrossingDialog(null)}
          onSubmit={handleCrossingSubmit}
          onDelete={crossingDialog.mode === 'edit' ? handleCrossingDelete : undefined}
        />
      )}
    </div>
  )
}
