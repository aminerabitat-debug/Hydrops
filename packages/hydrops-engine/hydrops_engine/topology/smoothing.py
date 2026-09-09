"""Lissage du profil altimetrique brut (cdc §6 : 'conservation du profil brut et generation d'un
profil lisse'). Moyenne mobile symetrique a fenetre fixe en metres : simple, deterministe,
suffisant pour filtrer le bruit DEM sans deplacer significativement les points hauts/bas reels.
"""

from __future__ import annotations


def moving_average_smooth(points: list[tuple[float, float]], window_m: float) -> list[tuple[float, float]]:
    """points: liste de (pk, z) triee par pk croissant. Retourne le profil lisse, meme nombre de points."""
    if window_m <= 0:
        return list(points)
    half = window_m / 2
    smoothed: list[tuple[float, float]] = []
    for pk_i, _ in points:
        window = [z for pk, z in points if pk_i - half <= pk <= pk_i + half]
        smoothed.append((pk_i, sum(window) / len(window)))
    return smoothed
