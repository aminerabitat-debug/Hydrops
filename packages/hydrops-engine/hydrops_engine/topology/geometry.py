"""Calcul geodesique de base : distance haversine et PK cumule le long d'une trace WGS84.

Une formule haversine pure-Python est retenue plutot qu'une dependance (pyproj, geopy) :
suffisante a l'echelle d'une adduction (quelques dizaines de km) pour un usage APS, et
garde le moteur sans dependance C-extension (docs/architecture/07 §7.1 : moteur pur).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0


def haversine_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Distance great-circle entre deux points (lon, lat) en degres, en metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class Vertex:
    lon: float
    lat: float
    pk: float  # distance cumulee depuis l'origine de la trace, en metres


def cumulative_pk(coordinates: list[tuple[float, float]]) -> list[Vertex]:
    """PK cumule a chaque sommet d'une polyligne (lon, lat), origine = premier point (pk=0)."""
    if len(coordinates) < 2:
        raise ValueError("Une geometrie de trace necessite au moins 2 coordonnees")
    vertices = [Vertex(coordinates[0][0], coordinates[0][1], 0.0)]
    pk = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coordinates, coordinates[1:]):
        pk += haversine_distance_m(lon1, lat1, lon2, lat2)
        vertices.append(Vertex(lon2, lat2, pk))
    return vertices


def total_length_m(coordinates: list[tuple[float, float]]) -> float:
    return cumulative_pk(coordinates)[-1].pk


def interpolate_lonlat_at_pk(coordinates: list[tuple[float, float]], pk: float) -> tuple[float, float]:
    """Position (lon, lat) au PK donne, par interpolation lineaire entre les deux sommets KML
    d'origine qui l'encadrent (pk hors bornes -> ecrete a l'extremite correspondante). Utilise pour
    positionner un noeud (jonction) ajoute manuellement a un PK arbitraire (Lot 3 etape 1)."""
    vertices = cumulative_pk(coordinates)
    pk = max(0.0, min(pk, vertices[-1].pk))
    for v1, v2 in zip(vertices, vertices[1:]):
        if v1.pk <= pk <= v2.pk:
            span = v2.pk - v1.pk
            t = 0.0 if span <= 0 else (pk - v1.pk) / span
            return (v1.lon + t * (v2.lon - v1.lon), v1.lat + t * (v2.lat - v1.lat))
    return (vertices[-1].lon, vertices[-1].lat)


def interpolate_value_at_pk(samples: list[tuple[float, float]], pk: float) -> float:
    """Valeur au PK donne par interpolation lineaire dans une sequence [(pk, valeur), ...] triee
    par pk croissant (typiquement le profil altimetrique) ; pk hors bornes -> ecrete."""
    if not samples:
        raise ValueError("liste de points vide")
    pk = max(samples[0][0], min(pk, samples[-1][0]))
    for (pk1, v1), (pk2, v2) in zip(samples, samples[1:]):
        if pk1 <= pk <= pk2:
            span = pk2 - pk1
            t = 0.0 if span <= 0 else (pk - pk1) / span
            return v1 + t * (v2 - v1)
    return samples[-1][1]
