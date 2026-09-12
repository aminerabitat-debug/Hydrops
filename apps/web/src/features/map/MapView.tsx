// Carte SIG (cdc §6) — MapLibre GL JS (open-source, cf. docs/architecture/01 §1.3).
// Fond satellite Esri World Imagery, avec repli automatique vers OSM standard en cas d'echec
// repete des tuiles — meme source et meme strategie de resilience que la page de reference
// fournie par l'utilisateur (page_carte_profil_itineraire.html).
// Affiche les traces importees et un marqueur de survol synchronise avec le profil/la table (V1-02).

import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useMemo, useRef, useState } from 'react'

import { buildVertices, coordinatesForPkRange, interpolateLonLatAtPk, nearestPkForPoint } from '../../shared/geo'
import { isPlaceholderNode, nodeColor, nodeDisplayLabel, nodeInitials } from '../../shared/nodeLabels'
import { useAppStore } from '../../state/store'
import type { TraceGeometry } from '../../shared/types'

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

  const traces = useAppStore((s) => s.traces)
  const nodes = useAppStore((s) => s.nodes)
  const selectedTraceId = useAppStore((s) => s.selection.selectedTraceId)
  const setSelectedTrace = useAppStore((s) => s.setSelectedTrace)
  const hoveredPk = useAppStore((s) => s.selection.hoveredPk)
  const mapFocusRequest = useAppStore((s) => s.mapFocusRequest)
  const showCrossings = useAppStore((s) => s.showCrossings)

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
          marker.getElement().title = crossing.label ? `${crossing.kind} · ${crossing.label}` : crossing.kind
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

  return (
    <div className="map-view-wrap">
      <div ref={containerRef} className="map-view" />
      <button
        type="button"
        className={`map-info-toggle ${infoMode ? 'active' : ''}`}
        onClick={() => setInfoMode((v) => !v)}
        title="Afficher l'ID et le PK du piquet survolé"
        aria-label="Afficher l'ID et le PK du piquet survolé"
      >
        PK ?
      </button>
      {hoverInfo && (
        <div className="map-hover-tooltip" style={{ left: hoverInfo.x + 12, top: hoverInfo.y + 12 }}>
          {hoverInfo.text}
        </div>
      )}
    </div>
  )
}
