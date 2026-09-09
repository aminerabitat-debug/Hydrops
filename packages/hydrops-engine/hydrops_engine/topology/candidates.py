"""Detection automatique des points hauts/bas candidats sur le profil LISSE (cdc §6) :
'ce sont des candidats que l'utilisateur valide ou non' — jamais crees comme Node valide=True.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    pk: float
    z: float
    kind: str  # "high_point" | "low_point"


def detect_high_low_points(
    smoothed: list[tuple[float, float]], min_prominence: float = 0.5
) -> list[Candidate]:
    """Un point est candidat seulement s'il domine (ou est domine par) ses DEUX voisins d'au moins
    min_prominence metres — evite de remonter du bruit DEM residuel comme faux point structurant.
    """
    candidates: list[Candidate] = []
    n = len(smoothed)
    if n < 3:
        return candidates
    for i in range(1, n - 1):
        pk, z = smoothed[i]
        z_prev = smoothed[i - 1][1]
        z_next = smoothed[i + 1][1]
        if z - z_prev >= min_prominence and z - z_next >= min_prominence:
            candidates.append(Candidate(pk, z, "high_point"))
        elif z_prev - z >= min_prominence and z_next - z >= min_prominence:
            candidates.append(Candidate(pk, z, "low_point"))
    return candidates
