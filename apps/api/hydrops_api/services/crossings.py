"""Detection des traversees (routes/pistes/voies ferrees, canaux/rivieres/cours d'eau, batiments) —
consigne utilisateur : "afficher et masquer" sur la carte et le profil. Perimetre MVP, indicatif —
base OpenStreetMap (Overpass API), pas un releve topographique certifie (cf. reserve posee a
l'utilisateur) : la couverture/qualite des donnees varie selon la region, et aucun tag OSM dedie
n'existe pour une "chaaba" (cours d'eau intermittent nord-africain) — seuls les `waterway=*`
effectivement cartographies (y compris `intermittent=yes`) sont detectes.

Decoupe en deux etapes independantes (consigne testabilite) :
- `fetch_osm_features` : appel reseau a Overpass, retourne les elements bruts (dict).
- `compute_crossings` : geometrie pure (shapely), testable sans reseau avec des elements
  synthetiques.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

import httpx
from shapely.geometry import LineString, Point

from hydrops_engine.topology.geometry import cumulative_pk

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 25.0
# Overpass renvoie 406 Not Acceptable sans User-Agent explicite (regle anti-bot du serveur) —
# constate empiriquement, cf. httpx par defaut n'en envoie pas d'utilisable ici.
_REQUEST_HEADERS = {"User-Agent": "HydroPS/1.0 (hydraulic network design tool)", "Accept": "*/*"}

# Marge (degres) ajoutee autour de l'emprise (bounding box) de la trace avant interrogation
# Overpass — une traversee peut etre tres proche d'une extremite, une bbox exactement ajustee
# risquerait de la manquer si le tron de voie/cours d'eau depasse legerement.
BBOX_MARGIN_DEG = 0.01

CrossingKind = Literal["highway", "railway", "waterway", "building"]

# Ordre de priorite si un element (rarement) porte plusieurs de ces tags a la fois.
_KIND_TAGS: list[CrossingKind] = ["railway", "waterway", "building", "highway"]


@dataclass(frozen=True)
class OsmFeature:
    kind: CrossingKind
    label: Optional[str]
    coordinates: list[tuple[float, float]]  # (lon, lat)


@dataclass(frozen=True)
class Crossing:
    id: str
    kind: CrossingKind
    label: Optional[str]
    pk: float
    lon: float
    lat: float


def _overpass_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    return (
        f"[out:json][timeout:{int(OVERPASS_TIMEOUT_S)}];"
        f'(way["highway"]({bbox});way["railway"]({bbox});'
        f'way["waterway"]({bbox});way["building"]({bbox}););'
        "out geom;"
    )


def _feature_from_element(element: dict) -> Optional[OsmFeature]:
    tags = element.get("tags") or {}
    geometry = element.get("geometry")
    if not geometry:
        return None
    kind = next((k for k in _KIND_TAGS if k in tags), None)
    if kind is None:
        return None
    label = tags.get("name") or tags.get(kind)
    coordinates = [(pt["lon"], pt["lat"]) for pt in geometry if "lon" in pt and "lat" in pt]
    if len(coordinates) < 2:
        return None
    return OsmFeature(kind=kind, label=label, coordinates=coordinates)


async def fetch_osm_features(
    bbox: tuple[float, float, float, float], client: Optional[httpx.AsyncClient] = None
) -> list[OsmFeature]:
    """bbox = (south, west, north, east), en degres WGS84. Une seule requete Overpass — pas de
    cascade de fournisseurs (contrairement au DEM) : Overpass est la seule source publique
    pratique pour ces tags, une indisponibilite est donc remontee telle quelle a l'appelant."""
    south, west, north, east = bbox
    query = _overpass_query(
        south - BBOX_MARGIN_DEG, west - BBOX_MARGIN_DEG, north + BBOX_MARGIN_DEG, east + BBOX_MARGIN_DEG
    )
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=OVERPASS_TIMEOUT_S)
    try:
        response = await client.post(OVERPASS_URL, data={"data": query}, headers=_REQUEST_HEADERS)
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            await client.aclose()
    features = [_feature_from_element(el) for el in payload.get("elements", [])]
    return [f for f in features if f is not None]


def trace_bbox(coordinates: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    lons = [c[0] for c in coordinates]
    lats = [c[1] for c in coordinates]
    return (min(lats), min(lons), max(lats), max(lons))


def _pk_at_point(vertices: list, lon: float, lat: float) -> float:
    """PK par projection sur le SEGMENT de trace le plus proche (approximation planaire locale sur
    lon/lat, largement suffisante a l'echelle d'un point de croisement) — plus precis qu'un simple
    "sommet le plus proche" (cf. `nearestPkForPoint` cote frontend, utilise pour le survol) des que
    les sommets de la trace sont espaces (KML importe avec peu de points intermediaires)."""
    best_pk = vertices[0].pk
    best_dist = math.inf
    for v1, v2 in zip(vertices, vertices[1:]):
        dx, dy = v2.lon - v1.lon, v2.lat - v1.lat
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq <= 0:
            t = 0.0
        else:
            t = ((lon - v1.lon) * dx + (lat - v1.lat) * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
        proj_lon, proj_lat = v1.lon + t * dx, v1.lat + t * dy
        dist = (proj_lon - lon) ** 2 + (proj_lat - lat) ** 2
        if dist < best_dist:
            best_dist = dist
            best_pk = v1.pk + t * (v2.pk - v1.pk)
    return best_pk


def compute_crossings(trace_coordinates: list[tuple[float, float]], features: list[OsmFeature]) -> list[Crossing]:
    """Intersection geometrique (shapely) entre la trace et chaque element OSM — une ligne pour
    les voies/cours d'eau, et TOUJOURS une ligne (pas un polygone) pour un bâtiment : le contour
    suffit a detecter une entree/sortie de son emprise, et evite les soucis de validite de polygone
    (way non refermee, auto-intersection) hors perimetre de cette detection indicative."""
    if len(trace_coordinates) < 2:
        return []
    trace_line = LineString(trace_coordinates)
    vertices = cumulative_pk(trace_coordinates)
    crossings: list[Crossing] = []
    for feature in features:
        if len(feature.coordinates) < 2:
            continue
        feature_line = LineString(feature.coordinates)
        intersection = trace_line.intersection(feature_line)
        points: list[Point] = []
        if intersection.is_empty:
            continue
        if intersection.geom_type == "Point":
            points = [intersection]
        elif intersection.geom_type == "MultiPoint":
            points = list(intersection.geoms)
        elif intersection.geom_type in ("LineString", "MultiLineString", "GeometryCollection"):
            # Chevauchement (trace et voie quasi-paralleles) plutot qu'un croisement net — hors
            # perimetre MVP (pas de "traversee" ponctuelle a signaler), on l'ignore silencieusement.
            continue
        for point in points:
            pk = _pk_at_point(vertices, point.x, point.y)
            crossings.append(
                Crossing(
                    id=str(uuid.uuid4()),
                    kind=feature.kind,
                    label=feature.label,
                    pk=pk,
                    lon=point.x,
                    lat=point.y,
                )
            )
    crossings.sort(key=lambda c: c.pk)
    return crossings
