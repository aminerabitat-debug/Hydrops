// Utilitaires geometriques partages carte/table/profil — decoupage PK <-> coordonnees, pour rester
// coherent entre les vues (evite de dupliquer trois fois la meme interpolation, cf. DataTable.tsx
// avant extraction ici, Lot 3 etape 1f : navigation carte au clic dans l'arborescence).

const EARTH_RADIUS_M = 6_371_000

export interface Vertex {
  lon: number
  lat: number
  pk: number
}

// Exportee (consigne utilisateur : outil de mesure de distance sur la carte) — meme formule que
// celle utilisee en interne pour buildVertices, pas de duplication.
export function haversineDistanceM(lon1: number, lat1: number, lon2: number, lat2: number): number {
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

// PK par PROJECTION sur le segment le plus proche (consigne utilisateur : "quand je clique à 2
// endroits proches sur la carte... j'obtiens le même piquet" — l'ancienne version arrondissait au
// SOMMET le plus proche, une grossiere approximation des que deux sommets du tracé source (KML,
// souvent tres espaces) encadrent la zone cliquee : tout clic dans le meme "polygone de Voronoi"
// autour d'un sommet renvoyait exactement son PK, quel que soit l'endroit precis clique). Meme
// principe que le calcul equivalent cote backend (hydrops_api.services.crossings:_pk_at_point) :
// pour chaque segment [v1, v2], projeter le point clique dessus (parametre t clampe a [0,1]),
// garder la projection la plus proche, interpoler son PK — continu le long de TOUTE la trace, pas
// seulement aux sommets.
export function nearestPkForPoint(vertices: Vertex[], lon: number, lat: number): number {
  let bestPk = vertices[0].pk
  let bestDist = Infinity
  for (let i = 0; i < vertices.length - 1; i++) {
    const v1 = vertices[i]
    const v2 = vertices[i + 1]
    const dx = v2.lon - v1.lon
    const dy = v2.lat - v1.lat
    const segLenSq = dx * dx + dy * dy
    const t = segLenSq <= 0 ? 0 : Math.max(0, Math.min(1, ((lon - v1.lon) * dx + (lat - v1.lat) * dy) / segLenSq))
    const projLon = v1.lon + t * dx
    const projLat = v1.lat + t * dy
    const dist = (projLon - lon) ** 2 + (projLat - lat) ** 2
    if (dist < bestDist) {
      bestDist = dist
      bestPk = v1.pk + t * (v2.pk - v1.pk)
    }
  }
  return bestPk
}

// Accroche un PK au piquet REGULIER (echantillon DEM) le plus proche (consigne utilisateur : "le
// piquet bis correspond toujours a un piquet regulier... les changements de materiau/DN/classe
// ainsi que les contraintes et les ouvrages sont tous positionnes sur des piquets reguliers, le
// plus proche par rapport au point de clic de l'utilisateur") — sans cet accrochage, un clic pixel
// (profil) ou une projection carte (`nearestPkForPoint` ci-dessus, continue le long de la trace)
// tombe presque toujours a quelques metres d'un piquet reel, ce qui decalerait legerement la
// frontiere resolue cote moteur (cf. hydrops_api.routers.network:_constraint_boundary_pks).
// `samples` doit etre trie par `pk` croissant ; recherche lineaire, un seul appel par clic/
// selection — pas un cout recurrent.
export function snapPkToNearestSample(samples: { pk: number }[], pk: number): number {
  if (samples.length === 0) return pk
  let closest = samples[0].pk
  let bestDist = Math.abs(samples[0].pk - pk)
  for (let i = 1; i < samples.length; i++) {
    const dist = Math.abs(samples[i].pk - pk)
    if (dist < bestDist) {
      bestDist = dist
      closest = samples[i].pk
    }
  }
  return closest
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
