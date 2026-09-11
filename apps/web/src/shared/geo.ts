// Utilitaires geometriques partages carte/table/profil — decoupage PK <-> coordonnees, pour rester
// coherent entre les vues (evite de dupliquer trois fois la meme interpolation, cf. DataTable.tsx
// avant extraction ici, Lot 3 etape 1f : navigation carte au clic dans l'arborescence).

const EARTH_RADIUS_M = 6_371_000

export interface Vertex {
  lon: number
  lat: number
  pk: number
}

function haversineDistanceM(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180
  const dPhi = toRad(lat2 - lat1)
  const dLambda = toRad(lon2 - lon1)
  const a = Math.sin(dPhi / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLambda / 2) ** 2
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)))
}

export function buildVertices(coordinates: [number, number][]): Vertex[] {
  const vertices: Vertex[] = [{ lon: coordinates[0][0], lat: coordinates[0][1], pk: 0 }]
  let pk = 0
  for (let i = 0; i < coordinates.length - 1; i++) {
    const [lon1, lat1] = coordinates[i]
    const [lon2, lat2] = coordinates[i + 1]
    pk += haversineDistanceM(lon1, lat1, lon2, lat2)
    vertices.push({ lon: lon2, lat: lat2, pk })
  }
  return vertices
}

export function interpolateLonLatAtPk(vertices: Vertex[], pk: number): [number, number] {
  const clamped = Math.max(0, Math.min(pk, vertices[vertices.length - 1].pk))
  for (let i = 0; i < vertices.length - 1; i++) {
    const a = vertices[i]
    const b = vertices[i + 1]
    if (clamped >= a.pk && clamped <= b.pk) {
      const span = b.pk - a.pk
      const t = span === 0 ? 0 : (clamped - a.pk) / span
      return [a.lon + t * (b.lon - a.lon), a.lat + t * (b.lat - a.lat)]
    }
  }
  const last = vertices[vertices.length - 1]
  return [last.lon, last.lat]
}

// Sommet le plus proche (distance euclidienne en lon/lat, suffisant pour un survol interactif —
// pas une projection exacte sur le segment) d'un point donne — sert au petit bouton d'information
// carte/profil (consigne utilisateur : ID + PK du piquet survole).
export function nearestPkForPoint(vertices: Vertex[], lon: number, lat: number): number {
  let best = vertices[0]
  let bestDist = Infinity
  for (const v of vertices) {
    const d = (v.lon - lon) ** 2 + (v.lat - lat) ** 2
    if (d < bestDist) {
      bestDist = d
      best = v
    }
  }
  return best.pk
}

// Sous-ensemble de coordonnees [lon,lat] couvrant [pkStart, pkEnd] le long d'une trace (extremites
// interpolees + sommets intermediaires) — sert a calculer l'emprise carte d'un troncon au clic
// dans l'arborescence (ProjectTree -> MapView:mapFocusRequest).
export function coordinatesForPkRange(
  coordinates: [number, number][],
  pkStart: number,
  pkEnd: number,
): [number, number][] {
  const vertices = buildVertices(coordinates)
  const points: [number, number][] = [interpolateLonLatAtPk(vertices, pkStart)]
  for (const v of vertices) {
    if (v.pk > pkStart && v.pk < pkEnd) points.push([v.lon, v.lat])
  }
  points.push(interpolateLonLatAtPk(vertices, pkEnd))
  return points
}
