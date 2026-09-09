"""Orchestration du profil altimetrique : echantillonnage -> DEM -> lissage -> candidats.

Assemble hydrops_engine.topology (pur, deterministe) et le DemProvider (I/O) — cette couche de
service est volontairement DANS l'API, pas dans le moteur, puisqu'elle fait un appel reseau
(docs/architecture/07-calcul-hydraulique-optimisation.md §7.1 : le moteur reste sans effet de bord).
"""

from __future__ import annotations

from collections.abc import Callable

from hydrops_engine.topology import detect_high_low_points, moving_average_smooth, sample_at_step

from .dem import DemProvider, fetch_elevations

DEFAULT_SAMPLE_STEP_M = 20.0
DEFAULT_SMOOTHING_WINDOW_M = 100.0
DEFAULT_MIN_PROMINENCE_M = 0.5


async def build_elevation_profile(
    coordinates: list[tuple[float, float]],
    dem_providers: list[DemProvider],
    sample_step_m: float = DEFAULT_SAMPLE_STEP_M,
    smoothing_window_m: float = DEFAULT_SMOOTHING_WINDOW_M,
    min_prominence_m: float = DEFAULT_MIN_PROMINENCE_M,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    samples = sample_at_step(coordinates, sample_step_m)
    result = await fetch_elevations([(v.lon, v.lat) for v in samples], dem_providers, on_progress=on_progress)
    elevations = result.elevations

    raw = [{"pk": v.pk, "z": z} for v, z in zip(samples, elevations)]

    smoothed_pairs = moving_average_smooth([(v.pk, z) for v, z in zip(samples, elevations)], smoothing_window_m)
    smoothed = [{"pk": pk, "z": z} for pk, z in smoothed_pairs]

    candidates = detect_high_low_points(smoothed_pairs, min_prominence=min_prominence_m)
    candidate_high_points = [{"pk": c.pk, "z": c.z} for c in candidates if c.kind == "high_point"]
    candidate_low_points = [{"pk": c.pk, "z": c.z} for c in candidates if c.kind == "low_point"]

    return {
        "dem_source": result.source_name,
        "dem_version": result.source_version,
        "raw": raw,
        "smoothed": smoothed,
        "candidate_high_points": candidate_high_points,
        "candidate_low_points": candidate_low_points,
    }
