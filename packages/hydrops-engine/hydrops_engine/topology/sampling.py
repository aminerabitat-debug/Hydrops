"""Echantillonnage regulier d'une polyligne le long du PK, pour le profil altimetrique (cdc §6)."""

from __future__ import annotations

from .geometry import Vertex, cumulative_pk


def sample_at_step(coordinates: list[tuple[float, float]], step_m: float) -> list[Vertex]:
    """Points regulierement espaces de step_m le long de la trace, plus chaque sommet d'origine
    (rupture de geometrie) et le point final — pour ne jamais manquer un changement de pente reel.
    """
    if step_m <= 0:
        raise ValueError("step_m doit etre > 0")
    vertices = cumulative_pk(coordinates)
    total = vertices[-1].pk

    targets: set[float] = set()
    pk = 0.0
    while pk < total:
        targets.add(round(pk, 6))
        pk += step_m
    targets.add(round(total, 6))
    for v in vertices:
        targets.add(round(v.pk, 6))

    return [_interpolate(vertices, pk) for pk in sorted(targets)]


def _interpolate(vertices: list[Vertex], pk: float) -> Vertex:
    first = vertices[0]
    if pk <= first.pk:
        return Vertex(first.lon, first.lat, pk)
    for a, b in zip(vertices, vertices[1:]):
        if a.pk <= pk <= b.pk:
            span = b.pk - a.pk
            t = 0.0 if span == 0 else (pk - a.pk) / span
            lon = a.lon + t * (b.lon - a.lon)
            lat = a.lat + t * (b.lat - a.lat)
            return Vertex(lon, lat, pk)
    last = vertices[-1]
    return Vertex(last.lon, last.lat, pk)
