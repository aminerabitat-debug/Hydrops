"""Validation de la topologie noeud/segment d'un reseau (cdc §5.2, §10) — Lot 3 etape 1.

Fonctions pures operant sur des tuples simples plutot que sur les modeles Pydantic hydropack :
hydrops-engine ne depend jamais de hydropack (docs/architecture/07-calcul-hydraulique-optimisation.md
§7.1, "moteur pur, sans effet de bord") — l'appelant (service API) convertit les modeles vers/
depuis ces types avant/apres l'appel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    node_id: Optional[str] = None
    segment_id: Optional[str] = None


def order_nodes_by_pk(nodes: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Trie (node_id, pk) par pk croissant. Ne mute pas l'entree."""
    return sorted(nodes, key=lambda n: n[1])


def validate_pk_strictly_increasing(nodes_ordered: list[tuple[str, float]]) -> list[Violation]:
    """`nodes_ordered` doit deja etre trie (order_nodes_by_pk) — detecte les PK dupliques ou non
    strictement croissants, qui produiraient des segments de longueur nulle ou negative."""
    violations: list[Violation] = []
    for (id_a, pk_a), (id_b, pk_b) in zip(nodes_ordered, nodes_ordered[1:]):
        if pk_b <= pk_a:
            violations.append(
                Violation(
                    code="DUPLICATE_OR_DECREASING_PK",
                    message=f"PK non strictement croissant entre noeuds {id_a} (pk={pk_a}) et {id_b} (pk={pk_b})",
                    node_id=id_b,
                )
            )
    return violations


# Types de noeud consideres comme des limites "dures" de troncon (cdc §8 : vrais ouvrages, plus
# les extremites de trace) — Piquage (tie_in) et Jonction simple sont transparents : plusieurs
# segments consecutifs entre deux limites dures se regroupent en UN SEUL troncon dans l'arborescence
# (decision utilisateur, Lot 3 etape 1b), meme si leur DN differe d'un segment a l'autre.
BOUNDARY_NODE_TYPES = frozenset({"terminal", "reservoir", "pumping_station", "pressure_break", "treatment_plant"})


@dataclass(frozen=True)
class TronconGroup:
    start_node_id: str
    end_node_id: str
    segment_ids: tuple[str, ...]
    pk_start: float
    pk_end: float


def group_into_troncons(
    nodes_ordered: list[tuple[str, str, float]],
    segment_by_edge: dict[tuple[str, str], str],
) -> list[TronconGroup]:
    """`nodes_ordered` : [(node_id, node_type, pk), ...] tries par pk croissant, pour UNE trace.
    `segment_by_edge` : {(upstream_node_id, downstream_node_id): segment_id} pour les aretes
    directes entre noeuds adjacents. Regroupe les segments consecutifs entre deux noeuds de type
    BOUNDARY_NODE_TYPES en un seul TronconGroup — le dernier maillon ferme toujours un troncon,
    meme si le dernier noeud n'est pas un type limite (garde-fou : aucun segment ne doit rester
    silencieusement hors de tout troncon)."""
    if len(nodes_ordered) < 2:
        return []
    groups: list[TronconGroup] = []
    start_idx = 0
    segment_ids: list[str] = []
    last_edge_idx = len(nodes_ordered) - 2
    for i in range(len(nodes_ordered) - 1):
        node_id = nodes_ordered[i][0]
        next_id, next_type, _ = nodes_ordered[i + 1]
        segment_id = segment_by_edge.get((node_id, next_id))
        if segment_id is not None:
            segment_ids.append(segment_id)
        if next_type in BOUNDARY_NODE_TYPES or i == last_edge_idx:
            groups.append(
                TronconGroup(
                    start_node_id=nodes_ordered[start_idx][0],
                    end_node_id=next_id,
                    segment_ids=tuple(segment_ids),
                    pk_start=nodes_ordered[start_idx][2],
                    pk_end=nodes_ordered[i + 1][2],
                )
            )
            start_idx = i + 1
            segment_ids = []
    return groups


def validate_non_increasing_di(segments_in_order: list[tuple[str, float]]) -> list[Violation]:
    """`segments_in_order` : [(segment_id, di), ...] dans l'ordre topologique amont->aval sur un
    meme chemin. Contrainte structurante cdc §10 : le diametre interieur ne doit jamais croitre
    vers l'aval — c'est une regle de validation du reseau, pas seulement une heuristique
    d'optimisation (docs/architecture/03-modele-donnees.md §3.6)."""
    violations: list[Violation] = []
    for (id_a, di_a), (id_b, di_b) in zip(segments_in_order, segments_in_order[1:]):
        if di_b > di_a:
            violations.append(
                Violation(
                    code="DI_INCREASES_DOWNSTREAM",
                    message=f"Le DI augmente vers l'aval entre segment {id_a} (DI={di_a}) et {id_b} (DI={di_b})",
                    segment_id=id_b,
                )
            )
    return violations
