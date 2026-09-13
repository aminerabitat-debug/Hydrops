"""Noeuds et segments (cdc §5.2, §7, §8, §10) — Lot 3 etape 1/1b.

Perimetre volontairement restreint : types de noeud `terminal` (auto, extremites de trace),
`junction` (decoupe un segment en deux sans etre un ouvrage), `tie_in`/`reservoir`/
`pumping_station`/`pressure_break`/`treatment_plant` (ouvrages "legers", taggage du type
seulement — la mise en donnees detaillee par ouvrage, cdc §8, arrive plus tard). Points hauts/bas
et vannes restent exclus (consigne utilisateur). Le calcul hydraulique arrive a l'etape suivante.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from hydropack.models import MaterialCriterionRule, Node, Segment, SegmentConstraint, SegmentDetail
from hydropack.serializer import ProjectPackage

from hydrops_engine.hydraulics import (
    EXCLUSION_ZONE_ALERT_MARKER,
    MIN_PRESSURE_ALERT_MARKER,
    CatalogPipe as HCatalogPipe,
    SegmentSpec as HSegmentSpec,
    solve_gravitaire_troncon,
    solve_refoulement_troncon,
)
from hydrops_engine.topology import (
    group_into_troncons,
    interpolate_lonlat_at_pk,
    interpolate_value_at_pk,
    validate_non_increasing_di,
    validate_pk_strictly_increasing,
)

from ..core.deps import get_session_store, require_package
from ..data.material_criteria_seed import DEFAULT_MATERIAL_CRITERIA
from ..data.pipe_catalog_seed import DEFAULT_ROUGHNESS_MM
from ..schemas import (
    NewNodeRequest,
    PatchNodePositionRequest,
    PatchNodeRequest,
    PatchSegmentRequest,
    PutSegmentConstraintsRequest,
)
from ..services import catalog

# Regime hydraulique d'un troncon (miroir exact de apps/web/src/shared/troncons.ts:tronconRegime —
# seul le noeud de DEPART compte, une jonction/piquage simple n'y figure jamais).
_PUMPING_TRIGGER_TYPES = frozenset({"pumping_station", "treatment_plant"})
_REAL_OUVRAGE_TYPES = frozenset(
    {"storage_reservoir", "surge_reservoir", "pumping_station", "pressure_break", "treatment_plant", "tie_in"}
)


def _troncon_regime(start_node: Optional[Node]) -> str:
    if start_node is None or start_node.type not in _REAL_OUVRAGE_TYPES:
        return "indetermine"
    return "refoulement" if start_node.type in _PUMPING_TRIGGER_TYPES else "gravitaire"


def _flow_by_node_within_troncon(troncon_node_ids: list[str], nodes_by_id: dict[str, Node], head_flow_m3h: float) -> dict[str, float]:
    """Debit (m3/h) porte par le segment en AVAL de chaque noeud d'UN troncon, a partir de son
    propre debit de tete (Segment.head_flow, saisi depuis la fenetre "Modifier le troncon" — quel
    que soit le regime, consigne utilisateur), ajuste a chaque piquage interne (+injected_flow /
    -withdrawn_flow si la case "prise en compte du prelevement" est cochee, cf.
    data.include_withdrawal_in_sizing). Un piquage est toujours un noeud INTERIEUR d'un troncon
    (jamais son debut/sa fin — cf. BOUNDARY_NODE_TYPES), donc ce parcours amont->aval suffit,
    independamment du sens utilise pour le calcul des pressions (gravitaire vs refoulement)."""
    result: dict[str, float] = {}
    current = head_flow_m3h
    for nid in troncon_node_ids:
        node = nodes_by_id[nid]
        if node.type == "tie_in":
            include = not (node.data and node.data.get("include_withdrawal_in_sizing") is False)
            if include and node.withdrawn_flow:
                current -= node.withdrawn_flow
            if node.injected_flow:
                current += node.injected_flow
        result[nid] = current
    return result


# Garde-fou (consigne utilisateur, glossaire Piquet/Segment/Troncon) : nombre max de piquets fins
# par Segment reel, quel que soit `hydraulic_segment_step_m` configure — l'optimisation
# telescopique (hydrops_engine) reessaie plusieurs paliers de DN par piquet ajoute, un pas trop fin
# sur un tres long troncon degraderait sinon la performance du calcul synchrone.
_MAX_FINE_SEGMENTS_PER_SEGMENT = 300


def _hydraulic_subdivision_points(
    pk_start: float, pk_end: float, profile_points: list, step_m: float
) -> list[tuple[float, float]]:
    """Points DEM (pk, z) strictement entre pk_start et pk_end, sous-echantillonnes au pas
    hydraulique configure (Preferences.hydraulic_segment_step_m) — reutilise les altitudes DEM
    telles quelles (deja echantillonnees tous les ~20 m par profile_builder.py), sans interpolation.
    Chaque point retenu devient un piquet virtuel supplementaire pour le moteur de calcul (cf.
    run_calculation), lui permettant de choisir un DN different par piquet (glossaire Piquet/
    Segment/Troncon, consigne utilisateur) — au lieu d'un DN unique pour tout le Segment reel."""
    interior = [(p.pk, p.z) for p in profile_points if pk_start + 1e-6 < p.pk < pk_end - 1e-6]
    if len(interior) < 2:
        return interior
    dem_step = interior[1][0] - interior[0][0]
    stride = max(1, round(step_m / dem_step)) if dem_step > 0 else 1
    sampled = interior[::stride]
    if len(sampled) > _MAX_FINE_SEGMENTS_PER_SEGMENT:
        coarser_stride = -(-len(interior) // _MAX_FINE_SEGMENTS_PER_SEGMENT)  # arrondi au superieur
        sampled = interior[::coarser_stride]
    return sampled


def _effective_constraints(first_seg: Segment) -> list[SegmentConstraint]:
    """Contraintes matériau/DN/classe par plage de PK d'un tronçon (consigne utilisateur) — celles
    de `first_seg.constraints`, precedees (compatibilite ascendante) d'une contrainte implicite
    SANS BORNES derivee de l'ancien forçage unique `forced_material`/`forced_dn` s'il est encore
    renseigne sur un projet existant (aucune migration de donnees necessaire : les deux mecanismes
    se combinent via la resolution "plage la plus etroite gagne", cf. _resolve_constraints_at_pk)."""
    constraints = list(first_seg.constraints)
    if first_seg.forced_material is not None or first_seg.forced_dn is not None:
        constraints = [
            SegmentConstraint(id="__legacy_forced__", material=first_seg.forced_material, dn=first_seg.forced_dn)
        ] + constraints
    return constraints


def _constraint_span(constraint: SegmentConstraint, troncon_pk_start: float, troncon_pk_end: float) -> tuple[float, float]:
    start = constraint.pk_start if constraint.pk_start is not None else troncon_pk_start
    end = constraint.pk_end if constraint.pk_end is not None else troncon_pk_end
    return start, end


def _resolve_constraints_at_pk(
    constraints: list[SegmentConstraint], pk: float, troncon_pk_start: float, troncon_pk_end: float
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Materiau/DN/classe effectifs a CE piquet (consigne utilisateur, contraintes par plage de
    PK) : pour chaque champ independamment, retient la valeur de la contrainte dont la plage est
    la plus ETROITE qui le renseigne et qui contient ce PK — une contrainte plus specifique ecrase
    une contrainte plus large, champ par champ (permet "FD partout" + "DN500 seulement entre 1550
    et 5664" : deux contraintes distinctes, chacune ne renseignant qu'un champ)."""
    best: dict[str, tuple[float, object]] = {}
    for constraint in constraints:
        start, end = _constraint_span(constraint, troncon_pk_start, troncon_pk_end)
        if not (start - 1e-6 <= pk <= end + 1e-6):
            continue
        width = end - start
        for field, value in (
            ("material", constraint.material), ("dn", constraint.dn), ("pressure_class", constraint.pressure_class),
        ):
            if value is None:
                continue
            current = best.get(field)
            # A largeur EGALE, la contrainte la plus RECENTE (derniere de la liste) l'emporte — la
            # contrainte implicite issue de l'ancien forced_material/forced_dn (compatibilite
            # ascendante, toujours en tete de liste, cf. _effective_constraints) a la meme largeur
            # "tout le tronçon" qu'une nouvelle contrainte non bornee ajoutee depuis le panneau
            # Contraintes — celle-ci doit pouvoir la remplacer, pas rester bloquee derriere elle.
            if current is None or width < current[0] + 1e-9:
                best[field] = (width, value)
    return (
        best["material"][1] if "material" in best else None,
        best["dn"][1] if "dn" in best else None,
        best["pressure_class"][1] if "pressure_class" in best else None,
    )


def _find_contradictory_constraints(
    constraints: list[SegmentConstraint], troncon_pk_start: float, troncon_pk_end: float
) -> Optional[str]:
    """Rejette toute paire de contraintes dont les plages se CROISENT partiellement (ni l'une ni
    l'autre entierement contenue dans l'autre) et qui renseignent toutes les deux le MEME champ
    avec des valeurs differentes (consigne utilisateur : "s'assurer que les contraintes ne sont
    pas contradictoires"). Deux plages strictement imbriquees restent autorisees — c'est le
    mecanisme de specificite de _resolve_constraints_at_pk. Retourne un message d'erreur explicite,
    ou None si tout va bien."""
    for i, a in enumerate(constraints):
        a_start, a_end = _constraint_span(a, troncon_pk_start, troncon_pk_end)
        for b in constraints[i + 1 :]:
            b_start, b_end = _constraint_span(b, troncon_pk_start, troncon_pk_end)
            overlap_start, overlap_end = max(a_start, b_start), min(a_end, b_end)
            if overlap_end <= overlap_start + 1e-6:
                continue
            a_contains_b = a_start <= b_start + 1e-6 and b_end <= a_end + 1e-6
            b_contains_a = b_start <= a_start + 1e-6 and a_end <= b_end + 1e-6
            if a_contains_b or b_contains_a:
                continue
            for field_label, va, vb in (
                ("matériau", a.material, b.material),
                ("DN", a.dn, b.dn),
                ("classe de pression", a.pressure_class, b.pressure_class),
            ):
                if va is not None and vb is not None and va != vb:
                    return (
                        f"Contraintes contradictoires sur le {field_label} entre PK {a_start:.0f}-{a_end:.0f} "
                        f"({va}) et PK {b_start:.0f}-{b_end:.0f} ({vb}) — leurs plages se croisent sans que "
                        f"l'une ne soit entièrement contenue dans l'autre."
                    )
    return None


_ENDPOINT_PK_TOLERANCE_M = 1e-6

router = APIRouter(prefix="/projects/{session_id}/variants/{variant_id}", tags=["network"])


def _require_variant(package: ProjectPackage, variant_id: str):
    variant = package.variants.get(variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="variante inconnue")
    return variant


def _nodes_for_variant(package: ProjectPackage, variant) -> list[Node]:
    variant_id = str(variant.id)
    nodes = [n for n in package.nodes.values() if str(n.variant_id) == variant_id]
    return sorted(nodes, key=lambda n: (str(n.trace_id), n.pk))


def _segments_for_variant(package: ProjectPackage, package_nodes: list[Node]) -> list[Segment]:
    node_ids = {str(n.id) for n in package_nodes}
    segments = [s for s in package.segments.values() if str(s.upstream_node_id) in node_ids]
    return sorted(segments, key=lambda s: s.pk_start)


def _reset_node_calc_fields(package: ProjectPackage, node_id: str) -> None:
    """Efface les sorties du calcul hydraulique portees par un noeud (cote piezo, pressions) —
    appele des qu'un segment adjacent voit ses donnees modifiees ou reinitialisees (consigne
    utilisateur), pour ne jamais laisser un resultat perime affiche dans le profil Data."""
    node = package.nodes.get(node_id)
    if node is None:
        return
    package.nodes[node_id] = node.model_copy(
        update={
            "piezo_head": None,
            "pressure_dynamic": None,
            "pressure_static_max": None,
            "pressure_static_min": None,
        }
    )


def _is_structural_endpoint(package: ProjectPackage, node: Node) -> bool:
    """Un noeud est une extremite STRUCTURELLE de trace (indeletable, meme s'il porte desormais un
    ouvrage — consigne utilisateur, Lot 3 etape 1c) si son PK correspond a 0 ou a la longueur de sa
    trace — independant de son `type`, qui peut changer (ex. terminal -> reservoir)."""
    trace_entry = package.traces.get(str(node.trace_id))
    if trace_entry is None:
        return False
    trace = trace_entry.geometry
    return node.pk <= _ENDPOINT_PK_TOLERANCE_M or node.pk >= trace.length - _ENDPOINT_PK_TOLERANCE_M


def _find_reposition_candidate_pk(
    current_pk: float,
    lower_bound: float,
    upper_bound: float,
    troncon_end_pk: float,
    offset: Optional[float],
    absolute_level: Optional[float],
    terrain: list[tuple[float, float]],
) -> Optional[float]:
    """Cherche, parmi les points de terrain echantillonnes strictement entre `lower_bound` et
    `upper_bound` (les voisins immediats du noeud sur sa trace — mêmes bornes que
    patch_node_position), le pk le plus proche de `current_pk` ou` placer le reservoir rendrait le
    tronçon a nouveau compatible : aucun point de terrain entre ce pk et `troncon_end_pk` ne
    depasse la cote effective a cette position (consigne utilisateur — proposer un deplacement au
    lieu de seulement alerter). Cote effective : si une saisie relative (`offset` non-null) a ete
    utilisee, elle suit le terrain (recalculee a chaque candidat) ; sinon la cote ABSOLUE saisie
    reste fixe quel que soit le candidat teste (elle n'est jamais recalculee automatiquement —
    consigne utilisateur)."""
    if offset is None and absolute_level is None:
        return None
    in_range = [(pk, z) for pk, z in terrain if lower_bound < pk < upper_bound]
    if not in_range:
        return None

    def effective_level(pk: float) -> float:
        if offset is not None:
            return interpolate_value_at_pk(terrain, pk) + offset
        return absolute_level  # type: ignore[return-value]

    def feasible(pk: float) -> bool:
        level = effective_level(pk)
        return all(z < level - 1e-6 for p, z in terrain if pk - 1e-6 <= p <= troncon_end_pk + 1e-6)

    best_pk: Optional[float] = None
    best_dist = float("inf")
    for pk, _ in in_range:
        if not feasible(pk):
            continue
        dist = abs(pk - current_pk)
        if dist < best_dist:
            best_pk, best_dist = pk, dist
    return best_pk


@router.get("/nodes")
def list_nodes(session_id: str, variant_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    return [n.model_dump(mode="json", exclude_none=True) for n in _nodes_for_variant(package, variant)]


@router.get("/segments")
def list_segments(session_id: str, variant_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    return [s.model_dump(mode="json", exclude_none=True) for s in _segments_for_variant(package, nodes)]


@router.get("/network/violations")
def get_network_violations(session_id: str, variant_id: str, request: Request):
    """Contraintes structurantes cdc §5.2/§10 : PK strictement croissant par trace, DI
    non-croissant vers l'aval sur chaque trace — une regle de validation du reseau, pas
    seulement une heuristique d'optimisation (docs/architecture/03-modele-donnees.md §3.6)."""
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    segments = _segments_for_variant(package, nodes)

    violations = []
    by_trace: dict[str, list[Node]] = {}
    for n in nodes:
        by_trace.setdefault(str(n.trace_id), []).append(n)
    for trace_nodes in by_trace.values():
        pairs = [(str(n.id), n.pk) for n in trace_nodes]
        violations += validate_pk_strictly_increasing(pairs)

    di_pairs = [(str(s.id), s.di) for s in segments]
    violations += validate_non_increasing_di(di_pairs)

    return [
        {"code": v.code, "message": v.message, "node_id": v.node_id, "segment_id": v.segment_id}
        for v in violations
    ]


@router.get("/network/troncons")
def list_troncons(session_id: str, variant_id: str, request: Request):
    """Regroupe les segments consecutifs entre deux limites "dures" (ouvrages reels ou extremite
    de trace) en troncons pour l'arborescence (cdc, decision utilisateur Lot 3 etape 1b) — Piquage
    et Jonction simple sont transparents et ne coupent pas un troncon."""
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    segments = _segments_for_variant(package, nodes)

    by_trace: dict[str, list[Node]] = {}
    for n in nodes:
        by_trace.setdefault(str(n.trace_id), []).append(n)
    segment_by_edge = {(str(s.upstream_node_id), str(s.downstream_node_id)): str(s.id) for s in segments}

    result = []
    for trace_id, trace_nodes in by_trace.items():
        ordered = [(str(n.id), n.type, n.pk) for n in sorted(trace_nodes, key=lambda n: n.pk)]
        for group in group_into_troncons(ordered, segment_by_edge):
            result.append(
                {
                    "trace_id": trace_id,
                    "start_node_id": group.start_node_id,
                    "end_node_id": group.end_node_id,
                    "segment_ids": list(group.segment_ids),
                    "pk_start": group.pk_start,
                    "pk_end": group.pk_end,
                }
            )
    return result


@router.post("/nodes", status_code=201)
def add_node(session_id: str, variant_id: str, payload: NewNodeRequest, request: Request):
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    trace_entry = package.traces.get(payload.trace_id)
    if trace_entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")
    trace = trace_entry.geometry

    if not (0.0 < payload.pk < trace.length):
        raise HTTPException(status_code=422, detail="pk doit etre strictement entre 0 et la longueur de la trace")

    nodes = _nodes_for_variant(package, variant)
    trace_nodes = [n for n in nodes if str(n.trace_id) == payload.trace_id]
    for n in trace_nodes:
        if abs(n.pk - payload.pk) < 1e-6:
            raise HTTPException(status_code=422, detail="un noeud existe deja a ce PK")

    segments = _segments_for_variant(package, nodes)
    enclosing = next((s for s in segments if s.pk_start <= payload.pk <= s.pk_end), None)
    if enclosing is None:
        raise HTTPException(status_code=409, detail="aucun segment ne couvre ce PK — reseau incomplet")

    lon, lat = interpolate_lonlat_at_pk(
        [(c[0], c[1]) for c in trace.geometry.coordinates], payload.pk
    )
    if trace.elevation_profile and trace.elevation_profile.raw:
        z = interpolate_value_at_pk([(p.pk, p.z) for p in trace.elevation_profile.raw], payload.pk)
    else:
        z = 0.0

    node = Node(
        id=uuid.uuid4(),
        trace_id=trace.id,
        variant_id=uuid.UUID(variant_id),
        type=payload.type,
        name=payload.name,
        pk=payload.pk,
        x=lon,
        y=lat,
        z=z,
        z_source="dem",
        data=payload.data,
        injected_flow=payload.injected_flow,
        withdrawn_flow=payload.withdrawn_flow,
        existing=payload.existing,
        phase_id=payload.phase_id,
    )
    package.nodes[str(node.id)] = node

    # forced=False (jamais copie de enclosing.forced) : les deux troncons issus de la scission
    # n'ont jamais ete valides independamment (forced_material/forced_dn, eux, repartent aussi a
    # None par defaut ci-dessous) — sinon l'arborescence les affichait "verts"/valides
    # (tronconIsForced) alors qu'aucun calcul n'a encore ete relance depuis la scission.
    upstream_seg = Segment(
        id=uuid.uuid4(),
        upstream_node_id=enclosing.upstream_node_id,
        downstream_node_id=node.id,
        pk_start=enclosing.pk_start,
        pk_end=payload.pk,
        length=payload.pk - enclosing.pk_start,
        material=enclosing.material,
        dn=enclosing.dn,
        di=enclosing.di,
        de=enclosing.de,
        pressure_class=enclosing.pressure_class,
        roughness=enclosing.roughness,
        flow=enclosing.flow,
        forced=False,
    )
    downstream_seg = Segment(
        id=uuid.uuid4(),
        upstream_node_id=node.id,
        downstream_node_id=enclosing.downstream_node_id,
        pk_start=payload.pk,
        pk_end=enclosing.pk_end,
        length=enclosing.pk_end - payload.pk,
        material=enclosing.material,
        dn=enclosing.dn,
        di=enclosing.di,
        de=enclosing.de,
        pressure_class=enclosing.pressure_class,
        roughness=enclosing.roughness,
        flow=enclosing.flow,
        forced=False,
    )
    del package.segments[str(enclosing.id)]
    package.segments[str(upstream_seg.id)] = upstream_seg
    package.segments[str(downstream_seg.id)] = downstream_seg

    return node.model_dump(mode="json", exclude_none=True)


@router.patch("/nodes/{node_id}")
def patch_node(session_id: str, variant_id: str, node_id: str, payload: PatchNodeRequest, request: Request):
    """Retype/renomme un noeud existant — y compris une extremite structurelle de trace, qui peut
    desormais porter un ouvrage (consigne utilisateur, Lot 3 etape 1c) sans perdre sa protection
    contre la suppression (basee sur le PK, pas sur le type — cf. _is_structural_endpoint)."""
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    node = next((n for n in nodes if str(n.id) == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="noeud inconnu")

    updates: dict = {}
    if payload.type is not None:
        updates["type"] = payload.type
    if payload.name is not None:
        updates["name"] = payload.name or None
    if payload.data is not None:
        updates["data"] = payload.data
    if payload.injected_flow is not None:
        updates["injected_flow"] = payload.injected_flow
    if payload.withdrawn_flow is not None:
        updates["withdrawn_flow"] = payload.withdrawn_flow
    if payload.existing is not None:
        updates["existing"] = payload.existing
    if payload.phase_id is not None:
        updates["phase_id"] = payload.phase_id or None
    if not updates:
        return node.model_dump(mode="json", exclude_none=True)

    # Un changement de TYPE peut changer le regime hydraulique d'un troncon (reservoir <->
    # station de pompage) ET/OU la topologie meme du decoupage en troncons (un noeud qui
    # entre/sort de BOUNDARY_NODE_TYPES fusionne ou scinde des troncons, cf.
    # hydrops_engine.topology.network.group_into_troncons) — les parametres hydrauliques
    # eventuellement deja saisis pour l'ancien regime n'ont plus de sens, d'ou un reset COMPLET
    # (_reset_segment_to_default, y compris `forced`). Un changement de DATA/debit de piquage ne
    # change ni le regime ni la topologie — seul le DIMENSIONNEMENT (materiau/DN, issu du fluide
    # notamment) n'est plus garanti valide, les parametres saisis restent bons : reset plus etroit
    # (_reset_segment_calc_outputs, ne touche pas `forced`). Dans les deux cas, on capture les
    # segments touches par ce noeud AVANT (ancien type encore en place) et APRES (nouveau type
    # applique) le changement — l'union couvre fusion et scission aussi bien qu'un simple
    # changement de regime sans changement de frontiere. Un simple renommage (`name` seul) ne
    # touche a rien (cosmetique, consigne utilisateur).
    type_changed = payload.type is not None and payload.type != node.type
    data_changed = (
        (payload.data is not None and payload.data != node.data)
        or (payload.injected_flow is not None and payload.injected_flow != node.injected_flow)
        or (payload.withdrawn_flow is not None and payload.withdrawn_flow != node.withdrawn_flow)
    )
    impacted_segment_ids: set[str] = set()
    if type_changed or data_changed:
        impacted_segment_ids |= _segment_ids_touching_node(package, variant, str(node.trace_id), node_id, node.pk)

    updated = node.model_copy(update=updates)
    package.nodes[node_id] = updated

    if type_changed or data_changed:
        impacted_segment_ids |= _segment_ids_touching_node(package, variant, str(node.trace_id), node_id, node.pk)
        for segment_id in impacted_segment_ids:
            if type_changed:
                _reset_segment_to_default(package, segment_id)
            else:
                _reset_segment_calc_outputs(package, segment_id)
                segment = package.segments.get(segment_id)
                if segment is not None:
                    _reset_node_calc_fields(package, str(segment.upstream_node_id))
                    _reset_node_calc_fields(package, str(segment.downstream_node_id))

    return updated.model_dump(mode="json", exclude_none=True)


@router.patch("/nodes/{node_id}/position")
def patch_node_position(session_id: str, variant_id: str, node_id: str, payload: PatchNodePositionRequest, request: Request):
    """Deplace un noeud existant le long de sa trace (consigne utilisateur : proposer de decaler
    le reservoir amont d'un tronçon gravitaire sur une alerte de terrain incompatible avec sa cote
    hydrostatique — cf. reposition_suggestions dans run_calculation). Une extremite structurelle
    (pk 0/longueur) PEUT etre deplacee — c'est au contraire le cas le plus frequent en pratique (un
    reservoir amont demarre presque toujours au premier noeud de sa trace) — les bornes ci-dessous
    (0.0 / longueur de trace pour un noeud sans voisin de ce cote) l'autorisent deja naturellement.
    Refuse seulement sur un pk qui ne reste pas strictement entre les deux noeuds voisins immediats
    de la meme trace (jamais de croisement d'un autre noeud)."""
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    node = next((n for n in nodes if str(n.id) == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="noeud inconnu")

    trace_entry = package.traces.get(str(node.trace_id))
    if trace_entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")
    trace = trace_entry.geometry

    trace_nodes = sorted((n for n in nodes if str(n.trace_id) == str(node.trace_id)), key=lambda n: n.pk)
    idx = next(i for i, n in enumerate(trace_nodes) if str(n.id) == node_id)
    lower_bound = trace_nodes[idx - 1].pk if idx > 0 else 0.0
    upper_bound = trace_nodes[idx + 1].pk if idx < len(trace_nodes) - 1 else trace.length
    if not (lower_bound < payload.pk < upper_bound):
        raise HTTPException(
            status_code=422,
            detail=f"le pk doit rester strictement entre {lower_bound:.1f} et {upper_bound:.1f} (voisins immediats)",
        )

    lon, lat = interpolate_lonlat_at_pk([(c[0], c[1]) for c in trace.geometry.coordinates], payload.pk)
    if trace.elevation_profile and trace.elevation_profile.raw:
        z = interpolate_value_at_pk([(p.pk, p.z) for p in trace.elevation_profile.raw], payload.pk)
    else:
        z = 0.0

    updated_node = node.model_copy(update={"pk": payload.pk, "x": lon, "y": lat, "z": z})
    package.nodes[node_id] = updated_node

    segments = _segments_for_variant(package, nodes)
    upstream_seg = next((s for s in segments if str(s.downstream_node_id) == node_id), None)
    downstream_seg = next((s for s in segments if str(s.upstream_node_id) == node_id), None)

    needs_level_confirmation = False
    for seg in (s for s in (upstream_seg, downstream_seg) if s is not None):
        seg_updates: dict = {}
        if seg is upstream_seg:
            seg_updates["pk_end"] = payload.pk
            seg_updates["length"] = payload.pk - seg.pk_start
        else:
            seg_updates["pk_start"] = payload.pk
            seg_updates["length"] = seg.pk_end - payload.pk
        # `upstream_water_level_max/min` sont portes par le segment mais decrivent la cote du
        # noeud AMONT du tronçon (le reservoir) — seul `downstream_seg` (celui qui DEMARRE au
        # noeud deplace) a le noeud deplace comme upstream_node ; `upstream_seg` appartient a un
        # tronçon DIFFERENT (qui se termine ici), sa propre cote amont est ailleurs et ne doit
        # jamais changer suite a ce deplacement.
        if seg is downstream_seg:
            # Cote relative ("+N") : recalculee automatiquement a la nouvelle position (consigne
            # utilisateur). Cote absolue (offset null) mais deja renseignee : laissee telle quelle
            # ici, le frontend redemande confirmation/modification a l'utilisateur apres coup.
            if seg.upstream_water_level_max_offset is not None:
                seg_updates["upstream_water_level_max"] = z + seg.upstream_water_level_max_offset
            elif seg.upstream_water_level_max is not None:
                needs_level_confirmation = True
            if seg.upstream_water_level_min_offset is not None:
                seg_updates["upstream_water_level_min"] = z + seg.upstream_water_level_min_offset
            elif seg.upstream_water_level_min is not None:
                needs_level_confirmation = True
        updated_seg = seg.model_copy(update=seg_updates)
        package.segments[str(seg.id)] = updated_seg
        # La longueur du segment change (donc sa perte de charge) — tout resultat de calcul
        # precedent pour ce segment/ses noeuds n'est plus valide.
        _reset_segment_calc_outputs(package, str(updated_seg.id))
        _reset_node_calc_fields(package, str(updated_seg.upstream_node_id))
        _reset_node_calc_fields(package, str(updated_seg.downstream_node_id))

    return {
        "node": updated_node.model_dump(mode="json", exclude_none=True),
        "needs_level_confirmation": needs_level_confirmation,
    }


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(session_id: str, variant_id: str, node_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    node = next((n for n in nodes if str(n.id) == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="noeud inconnu")
    if _is_structural_endpoint(package, node):
        raise HTTPException(status_code=400, detail="une extremite de trace ne peut pas etre supprimee")

    segments = _segments_for_variant(package, nodes)
    upstream_seg = next((s for s in segments if str(s.downstream_node_id) == node_id), None)
    downstream_seg = next((s for s in segments if str(s.upstream_node_id) == node_id), None)
    if upstream_seg is None or downstream_seg is None:
        raise HTTPException(status_code=409, detail="segments adjacents introuvables — reseau incoherent")

    merged = Segment(
        id=uuid.uuid4(),
        upstream_node_id=upstream_seg.upstream_node_id,
        downstream_node_id=downstream_seg.downstream_node_id,
        pk_start=upstream_seg.pk_start,
        pk_end=downstream_seg.pk_end,
        length=upstream_seg.length + downstream_seg.length,
        material=upstream_seg.material,
        dn=upstream_seg.dn,
        di=upstream_seg.di,
        de=upstream_seg.de,
        pressure_class=upstream_seg.pressure_class,
        roughness=upstream_seg.roughness,
        flow=upstream_seg.flow,
        forced=upstream_seg.forced,
    )
    del package.segments[str(upstream_seg.id)]
    del package.segments[str(downstream_seg.id)]
    package.segments[str(merged.id)] = merged
    del package.nodes[node_id]


@router.patch("/segments/{segment_id}")
def patch_segment(session_id: str, variant_id: str, segment_id: str, payload: PatchSegmentRequest, request: Request):
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    segments = _segments_for_variant(package, nodes)
    segment = next((s for s in segments if str(s.id) == segment_id), None)
    if segment is None:
        raise HTTPException(status_code=404, detail="segment inconnu")

    # Contrainte Materiau/DN forcee (fenetre "Modifier le tronçon", consigne utilisateur) : prime
    # sur la logique material/dn/pressure_class ci-dessous (reservee a la correction manuelle
    # depuis le profil Data, jamais soumise en meme temps par le frontend). "" (chaine vide) sur
    # forced_material revient au dimensionnement automatique (meme convention que
    # PatchNodeRequest.name) ; une valeur non-vide exige forced_dn et resout immediatement la
    # classe de pression la moins chere disponible (sans egard au PMS, inconnu a ce stade — cf.
    # run_calculation qui alerte si le PMS n'est finalement pas respecte).
    forced_material_update: Optional[str] = None
    forced_dn_update: Optional[int] = None
    forced_touched = payload.forced_material is not None
    if forced_touched and payload.forced_material != "":
        if payload.forced_dn is None:
            raise HTTPException(status_code=422, detail="forced_dn requis avec forced_material")
        if not catalog.material_dn_exists(payload.forced_material, payload.forced_dn):
            raise HTTPException(
                status_code=422, detail=f"aucune conduite active {payload.forced_material} DN{payload.forced_dn}"
            )
        forced_material_update = payload.forced_material
        forced_dn_update = payload.forced_dn
        selection = catalog.resolve_forced_selection(payload.forced_material, payload.forced_dn)
        material, dn, pressure_class = selection["material"], selection["dn"], selection["pressure_class"]
        resolved = {"di": selection["di"], "de": selection["de"]}
        roughness = package.calculation_preferences.roughness_by_material.get(material, catalog.default_roughness(material))
    elif forced_touched:
        # forced_material == "" : retour au dimensionnement automatique, comme un segment jamais
        # contraint (meme repli que is_pure_hydraulic_edit ci-dessous).
        default = catalog.default_selection()
        material, dn, pressure_class = default["material"], default["dn"], default["pressure_class"]
        resolved = {"di": default["di"], "de": default["de"]}
        roughness = default["roughness"]
    else:
        # Materiau/DN/classe TOUS absents du payload = edition pure des parametres hydrauliques
        # (fenetre "Modifier le tronçon"), pas une correction manuelle de conduite depuis le profil
        # Data — dans ce cas, le dimensionnement affiche jusqu'ici n'est plus valide pour rien (il
        # provenait d'un calcul avec d'anciens parametres, ou du catalogue par defaut) et ne doit pas
        # etre conserve silencieusement : retour au catalogue par defaut, exactement comme un
        # segment jamais calcule (consigne utilisateur — "ne remplir qu'une fois le calcul abouti").
        # Un payload qui fournit au moins un des trois reste une correction manuelle intentionnelle,
        # traitee comme avant (resolution via le catalogue).
        is_pure_hydraulic_edit = payload.material is None and payload.dn is None and payload.pressure_class is None
        if is_pure_hydraulic_edit:
            default = catalog.default_selection()
            material, dn, pressure_class = default["material"], default["dn"], default["pressure_class"]
            resolved = {"di": default["di"], "de": default["de"]}
            roughness = default["roughness"]
        else:
            material = payload.material or segment.material
            pressure_class = payload.pressure_class or segment.pressure_class
            dn = payload.dn if payload.dn is not None else segment.dn
            try:
                resolved = catalog.resolve(material, dn, pressure_class)
            except catalog.CatalogLookupError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            roughness = package.calculation_preferences.roughness_by_material.get(material, catalog.default_roughness(material))

    # "force" marque desormais simplement "les donnees de ce troncon ont ete validees via la
    # fenetre Modifier" (consigne utilisateur : couleur du texte une fois valide/reinitialise) —
    # pas seulement un ecart par rapport au catalogue par defaut. Depuis l'ajout du calcul
    # hydraulique, Materiau/DN/Classe ne sont plus saisis QUE via cet endpoint (fenetre Modifier le
    # troncon ne les propose plus, consigne utilisateur — ils viennent soit du calcul, soit d'une
    # correction manuelle depuis le profil Data).
    # Toute modification des donnees du troncon invalide les resultats du dernier calcul pour ce
    # segment (consigne utilisateur : les colonnes "depuis Debit vers la droite" du profil Data ne
    # doivent jamais rester prereplies avec un resultat perime) — reinitialisees ici, elles ne
    # sont reposees que par un nouveau passage du bouton Calculer.
    updates: dict = {
        "material": material,
        "dn": dn,
        "pressure_class": pressure_class,
        "di": resolved["di"],
        "de": resolved["de"],
        "roughness": roughness,
        "forced": True,
        "flow": 0.0,
        "velocity": None,
        "head_loss_unit": None,
        "head_loss_segment": None,
        "head_loss_cumulative": None,
        "segment_details": None,
    }
    if payload.upstream_water_level_max is not None:
        updates["upstream_water_level_max"] = payload.upstream_water_level_max
        # L'offset (relatif "+N") est reenvoye a CHAQUE sauvegarde par le frontend (resolveLevelInput
        # le recalcule a chaque frappe) — toujours ecrase avec la cote, jamais laisse perime : None =
        # cote absolue cette fois-ci, meme si une saisie relative existait avant.
        updates["upstream_water_level_max_offset"] = payload.upstream_water_level_max_offset
    if payload.head_flow is not None:
        updates["head_flow"] = payload.head_flow
    if payload.upstream_water_level_min is not None:
        updates["upstream_water_level_min"] = payload.upstream_water_level_min
        updates["upstream_water_level_min_offset"] = payload.upstream_water_level_min_offset
    if payload.min_pressure is not None:
        updates["min_pressure"] = payload.min_pressure
    if payload.downstream_residual_pressure is not None:
        updates["downstream_residual_pressure"] = payload.downstream_residual_pressure
    if payload.min_pressure_exclusion_m is not None:
        updates["min_pressure_exclusion_m"] = payload.min_pressure_exclusion_m
    if payload.max_velocity is not None:
        updates["max_velocity"] = payload.max_velocity
    if payload.min_velocity is not None:
        updates["min_velocity"] = payload.min_velocity
    if forced_touched:
        updates["forced_material"] = forced_material_update
        updates["forced_dn"] = forced_dn_update
    if payload.phase_id is not None:
        updates["phase_id"] = payload.phase_id or None

    updated = segment.model_copy(update=updates)
    package.segments[segment_id] = updated
    _reset_node_calc_fields(package, str(updated.upstream_node_id))
    _reset_node_calc_fields(package, str(updated.downstream_node_id))
    return updated.model_dump(mode="json", exclude_none=True)


@router.post("/calcul")
def run_calculation(
    session_id: str,
    variant_id: str,
    request: Request,
    scope_trace_id: Optional[str] = None,
    scope_start_node_id: Optional[str] = None,
):
    """Bouton Calcul > Calculer (consigne utilisateur). Par defaut (variante selectionnee dans
    l'arborescence, aucun tronçon precis) : precondition inchangee, TOUS les tronçons de la
    variante (toutes traces confondues) doivent avoir un regime determine (pas "indetermine") ET
    etre valides (donnees hydrauliques enregistrees via "Modifier le troncon" — Segment.forced),
    sinon 409 avec la liste de ce qui manque — le calcul ne se lance pas partiellement. Si
    `scope_trace_id`/`scope_start_node_id` identifient un tronçon precis (consigne utilisateur :
    un tronçon deja selectionne et valide se calcule seul, sans exiger les autres) : SEUL ce
    tronçon est exige valide et (re)calcule, les autres tronçons de la variante restent inchanges."""
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    segments = _segments_for_variant(package, nodes)
    nodes_by_id: dict[str, Node] = {str(n.id): n for n in nodes}
    segments_by_id: dict[str, Segment] = {str(s.id): s for s in segments}

    by_trace: dict[str, list[Node]] = {}
    for n in nodes:
        by_trace.setdefault(str(n.trace_id), []).append(n)

    scoped_to_one_troncon = scope_trace_id is not None and scope_start_node_id is not None

    missing: list[str] = []
    troncons_by_trace: dict[str, list] = {}
    for tid, trace_nodes in by_trace.items():
        if scoped_to_one_troncon and tid != scope_trace_id:
            continue
        ordered = sorted(trace_nodes, key=lambda n: n.pk)
        ordered_tuples = [(str(n.id), n.type, n.pk) for n in ordered]
        segment_by_edge = {(str(s.upstream_node_id), str(s.downstream_node_id)): str(s.id) for s in segments}
        groups = group_into_troncons(ordered_tuples, segment_by_edge)
        if scoped_to_one_troncon:
            groups = [g for g in groups if g.start_node_id == scope_start_node_id]
        troncons_by_trace[tid] = groups
        for group in groups:
            start_node = nodes_by_id.get(group.start_node_id)
            end_node = nodes_by_id.get(group.end_node_id)
            regime = _troncon_regime(start_node)
            forced = bool(group.segment_ids) and all(segments_by_id[sid].forced for sid in group.segment_ids)
            if regime == "indetermine" or not forced:
                start_label = (start_node.name or start_node.type) if start_node else "?"
                end_label = (end_node.name or end_node.type) if end_node else "?"
                reason = "régime indéterminé" if regime == "indetermine" else "données non validées"
                missing.append(f"{start_label} → {end_label} ({reason})")
    if scoped_to_one_troncon and not any(troncons_by_trace.values()):
        raise HTTPException(status_code=404, detail="tronçon introuvable (données modifiées depuis la sélection ?)")
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                ("Le tronçon sélectionné doit être déterminé (régime connu) et validé (Modifier le "
                 "tronçon) avant de lancer le calcul. Manquant : " if scoped_to_one_troncon else
                 "Tous les tronçons doivent être déterminés (régime connu) et validés (Modifier le "
                 "tronçon) avant de lancer le calcul. Manquant : ") + "; ".join(missing)
            ),
        )

    prefs = package.calculation_preferences
    roughness_by_material = dict(DEFAULT_ROUGHNESS_MM)
    roughness_by_material.update(prefs.roughness_by_material)
    catalog_rows = [
        HCatalogPipe(
            id=r.id, dn=r.dn, di_mm=r.di, material=r.material, pressure_class=r.pressure_class,
            pms_m=r.pms, price=r.prix_aps, roughness_mm=roughness_by_material.get(r.material, 0.1),
            active=r.active,
        )
        for r in catalog.list_pipe_rows()
    ]
    criteria: list[MaterialCriterionRule] = prefs.material_criteria or [
        MaterialCriterionRule(**c) for c in DEFAULT_MATERIAL_CRITERIA
    ]

    def make_allowed_materials_fn(fluid: Optional[str]):
        def fn(dn: int) -> Optional[frozenset[str]]:
            matches = [
                c for c in criteria
                if (c.dn_min is None or dn >= c.dn_min)
                and (c.dn_max is None or dn <= c.dn_max)
                and (c.fluid is None or c.fluid == fluid)
            ]
            if not matches:
                return None
            allowed: set[str] = set()
            for m in matches:
                allowed.update(m.materials)
            return frozenset(allowed) if allowed else None

        return fn

    all_alerts: list[str] = []
    reposition_suggestions: list[dict] = []
    updated_segments = 0
    updated_nodes = 0

    for trace_id, troncon_groups in troncons_by_trace.items():
        trace_entry = package.traces.get(trace_id)
        profile_points = (
            trace_entry.geometry.elevation_profile.raw
            if trace_entry and trace_entry.geometry.elevation_profile
            else []
        )
        for group in troncon_groups:
            troncon_segments = [segments_by_id[sid] for sid in group.segment_ids]
            if not troncon_segments:
                continue
            start_node = nodes_by_id[group.start_node_id]
            regime = _troncon_regime(start_node)
            first_seg = troncon_segments[0]

            troncon_node_ids: list[str] = [str(troncon_segments[0].upstream_node_id)]
            troncon_node_ids += [str(seg.downstream_node_id) for seg in troncon_segments]
            node_ground_z = {nid: nodes_by_id[nid].z for nid in troncon_node_ids}
            node_pk = {nid: nodes_by_id[nid].pk for nid in troncon_node_ids}
            # Le profil de terrain (DEM) entre les noeuds reels peut cacher un point haut jamais
            # materialise par un noeud (consigne utilisateur : la pression minimale doit etre
            # verifiee sur le terrain, pas seulement aux deux extremites d'un troncon de plusieurs
            # kilometres) — cf. hydrops_engine.hydraulics:_check_terrain_pressure.
            terrain_samples = [
                (p.pk, p.z) for p in profile_points if group.pk_start - 1e-6 <= p.pk <= group.pk_end + 1e-6
            ]

            flow_by_node_id = _flow_by_node_within_troncon(troncon_node_ids, nodes_by_id, first_seg.head_flow or 0.0)

            fluid = start_node.data.get("fluid") if start_node.data else None
            allowed_fn = make_allowed_materials_fn(fluid if isinstance(fluid, str) else None)

            # Subdivision de chaque Segment reel en piquets fins (consigne utilisateur, glossaire
            # Piquet/Segment/Troncon : "le DN d'un tronçon [...] sera un tableau de DN, un par
            # piquet") — le moteur recoit ainsi une liste plus fine que les seuls ouvrages reels,
            # ce qui lui permet de choisir un DN different par piquet (optimisation telescopique
            # deja implementee dans hydrops_engine). Toujours subdivise, meme sous contrainte
            # matériau/DN/classe (consigne utilisateur : contraintes par PLAGE DE PK, cf.
            # _resolve_constraints_at_pk) — une contrainte SANS bornes (ex. l'ancien forçage unique)
            # resout alors simplement a la meme valeur sur tous les piquets, sans cas particulier.
            # `fine_parent_ids`/`fine_downstream_pk` permettent de regrouper les resultats fins par
            # Segment reel une fois le calcul termine (cf. plus bas).
            effective_constraints = _effective_constraints(first_seg)
            first_real_id = str(troncon_segments[0].upstream_node_id)
            fine_node_ids: list[str] = [first_real_id]
            fine_node_ground_z: dict[str, float] = {first_real_id: nodes_by_id[first_real_id].z}
            fine_node_pk: dict[str, float] = {first_real_id: nodes_by_id[first_real_id].pk}
            fine_specs: list[HSegmentSpec] = []
            fine_parent_ids: list[str] = []
            fine_downstream_pk: list[float] = []

            for seg in troncon_segments:
                upstream_id = str(seg.upstream_node_id)
                downstream_id = str(seg.downstream_node_id)
                seg_flow_m3s = flow_by_node_id.get(upstream_id, 0.0) / 3600.0
                subdivision = _hydraulic_subdivision_points(
                    seg.pk_start, seg.pk_end, profile_points, prefs.hydraulic_segment_step_m
                )

                prev_pk = seg.pk_start
                for i, (pk, z) in enumerate(subdivision):
                    virtual_id = f"{seg.id}::piquet::{i}"
                    fine_node_ids.append(virtual_id)
                    fine_node_ground_z[virtual_id] = z
                    fine_node_pk[virtual_id] = pk
                    forced_material, forced_dn, forced_pressure_class = _resolve_constraints_at_pk(
                        effective_constraints, pk, group.pk_start, group.pk_end
                    )
                    fine_specs.append(
                        HSegmentSpec(
                            id=f"{seg.id}::{len(fine_specs)}", length_m=pk - prev_pk, flow_m3s=seg_flow_m3s,
                            max_velocity_ms=first_seg.max_velocity, min_velocity_ms=first_seg.min_velocity,
                            forced_material=forced_material, forced_dn=forced_dn,
                            forced_pressure_class=forced_pressure_class,
                        )
                    )
                    fine_parent_ids.append(str(seg.id))
                    fine_downstream_pk.append(pk)
                    prev_pk = pk

                fine_node_ids.append(downstream_id)
                fine_node_ground_z[downstream_id] = nodes_by_id[downstream_id].z
                fine_node_pk[downstream_id] = seg.pk_end
                forced_material, forced_dn, forced_pressure_class = _resolve_constraints_at_pk(
                    effective_constraints, seg.pk_end, group.pk_start, group.pk_end
                )
                fine_specs.append(
                    HSegmentSpec(
                        id=f"{seg.id}::{len(fine_specs)}", length_m=seg.pk_end - prev_pk, flow_m3s=seg_flow_m3s,
                        max_velocity_ms=first_seg.max_velocity, min_velocity_ms=first_seg.min_velocity,
                        forced_material=forced_material, forced_dn=forced_dn,
                        forced_pressure_class=forced_pressure_class,
                    )
                )
                fine_parent_ids.append(str(seg.id))
                fine_downstream_pk.append(seg.pk_end)

            # Contrainte(s) matériau/DN/classe (fenetre "Modifier le tronçon", consigne
            # utilisateur) : le calcul doit s'appliquer meme si une contrainte de pression/vitesse
            # est violee — cf. plus bas, la reinitialisation-sur-alerte est alors sautee pour ce
            # tronçon (sauf absence totale de resultats exploitables, ex. alerte hydrostatique).
            troncon_has_forced_pipe = bool(effective_constraints)

            if regime == "gravitaire":
                result = solve_gravitaire_troncon(
                    node_ids_ordered=fine_node_ids,
                    node_ground_z=fine_node_ground_z,
                    segments_ordered=fine_specs,
                    upstream_level_max=first_seg.upstream_water_level_max or 0.0,
                    upstream_level_min=first_seg.upstream_water_level_min,
                    min_pressure=first_seg.min_pressure,
                    downstream_residual_pressure=first_seg.downstream_residual_pressure,
                    catalog=catalog_rows,
                    singular_loss_markup_pct=prefs.singular_loss_markup_pct,
                    fluid_temperature_c=prefs.fluid_temperature_c,
                    allowed_materials_fn=allowed_fn,
                    node_pk=fine_node_pk,
                    terrain_samples=terrain_samples,
                    min_pressure_exclusion_m=first_seg.min_pressure_exclusion_m,
                )
            else:
                result = solve_refoulement_troncon(
                    node_ids_ordered=fine_node_ids,
                    node_ground_z=fine_node_ground_z,
                    segments_ordered=fine_specs,
                    min_pressure=first_seg.min_pressure,
                    downstream_residual_pressure=first_seg.downstream_residual_pressure,
                    catalog=catalog_rows,
                    singular_loss_markup_pct=prefs.singular_loss_markup_pct,
                    fluid_temperature_c=prefs.fluid_temperature_c,
                    allowed_materials_fn=allowed_fn,
                    node_pk=fine_node_pk,
                    terrain_samples=terrain_samples,
                    min_pressure_exclusion_m=first_seg.min_pressure_exclusion_m,
                )

            all_alerts.extend(result.alerts)

            # Alertes "zone d'exclusion" et "pression minimale non garantie" : toujours informatives,
            # jamais bloquantes, quel que soit le tronçon (force ou non) — consigne utilisateur : "ne
            # bloque plus le calcul pour une question de pression minimale, affiche juste une
            # alerte". Le dimensionnement calcule (DN/materiau/vitesse) reste applique tel quel ;
            # seule une alerte hydrostatique (terrain au-dessus de la cote du reservoir, aucun
            # resultat exploitable — cf. plus bas, `result.segments` vide) reste bloquante.
            hard_alerts = [
                a for a in result.alerts
                if EXCLUSION_ZONE_ALERT_MARKER not in a and MIN_PRESSURE_ALERT_MARKER not in a
            ]
            if hard_alerts:
                # Alerte hydrostatique gravitaire (terrain incompatible avec la cote du reservoir
                # amont, cf. hydraulics.py:_check_hydrostatic_feasibility) : proposer de deplacer
                # le reservoir au pk compatible le plus proche plutot que de se contenter d'alerter
                # (consigne utilisateur) — y compris quand ce noeud est l'extremite structurelle de
                # la trace (pk 0), le cas le plus frequent en pratique pour un reservoir amont ; les
                # bornes ci-dessous l'autorisent deja a se deplacer vers l'aval jusqu'a son voisin
                # suivant, cf. patch_node_position.
                if regime == "gravitaire" and any("hydrostatique" in a.lower() for a in result.alerts):
                    trace_nodes_sorted = sorted(by_trace[trace_id], key=lambda n: n.pk)
                    idx = next(
                        (i for i, n in enumerate(trace_nodes_sorted) if str(n.id) == group.start_node_id), None
                    )
                    if idx is not None:
                        lower_bound = trace_nodes_sorted[idx - 1].pk if idx > 0 else 0.0
                        upper_bound = (
                            trace_nodes_sorted[idx + 1].pk
                            if idx < len(trace_nodes_sorted) - 1
                            else (trace_entry.geometry.length if trace_entry else group.pk_end)
                        )
                        candidate_pk = _find_reposition_candidate_pk(
                            current_pk=start_node.pk,
                            lower_bound=lower_bound,
                            upper_bound=upper_bound,
                            troncon_end_pk=group.pk_end,
                            offset=first_seg.upstream_water_level_min_offset,
                            absolute_level=first_seg.upstream_water_level_min,
                            terrain=[(p.pk, p.z) for p in profile_points],
                        )
                        if candidate_pk is not None:
                            reposition_suggestions.append(
                                {
                                    "node_id": group.start_node_id,
                                    "node_label": start_node.name or start_node.type,
                                    "current_pk": start_node.pk,
                                    "candidate_pk": candidate_pk,
                                }
                            )
                # Un troncon dont le calcul produit une alerte n'a "pas abouti sans erreur"
                # (consigne utilisateur) — aucun resultat partiel/degrade n'est applique : le
                # dimensionnement retombe au catalogue par defaut et les noeuds sont remis a zero
                # (memes helpers que la reinitialisation manuelle), pour ne jamais laisser un
                # Materiau/DN ou une ligne piezo perimee affichee. Les autres troncons continuent
                # normalement (le calcul global ne s'interrompt pas).
                # EXCEPTION (consigne utilisateur) : un tronçon a Materiau/DN force n'est jamais
                # reinitialise pour une alerte de pression/vitesse — le calcul s'applique quand
                # meme (l'alerte reste informative). Seule l'absence totale de resultats
                # exploitables (`result.segments` vide — alerte hydrostatique, precheck avant tout
                # dimensionnement) impose encore la reinitialisation, meme force.
                if not troncon_has_forced_pipe or not result.segments:
                    for seg in troncon_segments:
                        _reset_segment_calc_outputs(package, str(seg.id))
                        segments_by_id[str(seg.id)] = package.segments[str(seg.id)]
                    for nid in troncon_node_ids:
                        _reset_node_calc_fields(package, nid)
                        nodes_by_id[nid] = package.nodes[nid]
                    continue

            # Regroupement des resultats fins (un par piquet) par Segment reel parent — chaque
            # Segment reel recoit desormais un TABLEAU (`segment_details`, glossaire Piquet/
            # Segment/Troncon), le dernier piquet (le plus aval) etant aussi reflete dans les
            # champs scalaires existants pour compatibilite avec le reste de l'app.
            segment_details_by_real_id: dict[str, list[SegmentDetail]] = {}
            for parent_id, pk_value, seg_result in zip(fine_parent_ids, fine_downstream_pk, result.segments):
                segment_details_by_real_id.setdefault(parent_id, []).append(
                    SegmentDetail(
                        pk=pk_value,
                        material=seg_result.material,
                        pressure_class=seg_result.pressure_class,
                        dn=seg_result.dn,
                        di=seg_result.di_mm,
                        de=float(seg_result.dn),
                        roughness=seg_result.roughness_mm,
                        velocity=seg_result.velocity_ms,
                        head_loss_unit=seg_result.head_loss_unit,
                        head_loss_segment=seg_result.head_loss_segment,
                        head_loss_cumulative=seg_result.head_loss_cumulative,
                    )
                )

            for real_seg_id, details in segment_details_by_real_id.items():
                seg = segments_by_id[real_seg_id]
                last = details[-1]
                updated_seg = seg.model_copy(
                    update={
                        "material": last.material,
                        "pressure_class": last.pressure_class,
                        "dn": last.dn,
                        "di": last.di,
                        "de": last.de,
                        "roughness": last.roughness,
                        "flow": flow_by_node_id.get(str(seg.upstream_node_id), 0.0),
                        "velocity": last.velocity,
                        "head_loss_unit": last.head_loss_unit,
                        "head_loss_segment": last.head_loss_segment,
                        "head_loss_cumulative": last.head_loss_cumulative,
                        "segment_details": details,
                    }
                )
                package.segments[real_seg_id] = updated_seg
                segments_by_id[real_seg_id] = updated_seg
                updated_segments += 1

            for node_result in result.nodes:
                # Les piquets virtuels (subdivision fine, cf. plus haut) ne sont pas des `Node`
                # persistes — seuls les ouvrages reels recoivent une mise a jour ici.
                if node_result.node_id not in nodes_by_id:
                    continue
                node = nodes_by_id[node_result.node_id]
                updated_node = node.model_copy(
                    update={
                        "piezo_head": node_result.piezo_head,
                        "pressure_dynamic": node_result.pressure_dynamic,
                        "pressure_static_max": node_result.pressure_static_max,
                        "pressure_static_min": node_result.pressure_static_min,
                    }
                )
                package.nodes[node_result.node_id] = updated_node
                nodes_by_id[node_result.node_id] = updated_node
                updated_nodes += 1

    package.variants[variant_id] = variant.model_copy(update={"status": "calculated"})

    return {
        "status": "calculated",
        "segments_updated": updated_segments,
        "nodes_updated": updated_nodes,
        "alerts": all_alerts,
        "reposition_suggestions": reposition_suggestions,
    }


def _reset_segment_to_default(package: ProjectPackage, segment_id: str) -> Optional[Segment]:
    """Reinitialise un segment aux valeurs catalogue par defaut (materiau/DN/classe), et efface son
    statut 'force' — equivalent d'une "suppression" de la mise en donnees d'un troncon (consigne
    utilisateur) sans toucher a la topologie (noeuds/segments restent en place, seules leurs
    caracteristiques hydrauliques reviennent au defaut pose a l'import). Reutilise par l'endpoint
    "Réinitialiser le tronçon" ET par patch_node quand un changement de type d'ouvrage invalide les
    troncons impactes (consigne utilisateur)."""
    segment = package.segments.get(segment_id)
    if segment is None:
        return None
    default = catalog.default_selection()
    updated = segment.model_copy(
        update={
            "material": default["material"],
            "dn": default["dn"],
            "di": default["di"],
            "de": default["de"],
            "pressure_class": default["pressure_class"],
            "roughness": default["roughness"],
            "forced": False,
            "head_flow": None,
            "upstream_water_level_max": None,
            "upstream_water_level_min": None,
            "upstream_water_level_max_offset": None,
            "upstream_water_level_min_offset": None,
            "min_pressure": None,
            "downstream_residual_pressure": None,
            "min_pressure_exclusion_m": None,
            "max_velocity": None,
            "min_velocity": None,
            "forced_material": None,
            "forced_dn": None,
            "constraints": [],
            "flow": 0.0,
            "velocity": None,
            "head_loss_unit": None,
            "head_loss_segment": None,
            "head_loss_cumulative": None,
            "segment_details": None,
        }
    )
    package.segments[segment_id] = updated
    _reset_node_calc_fields(package, str(updated.upstream_node_id))
    _reset_node_calc_fields(package, str(updated.downstream_node_id))
    return updated


def _reset_segment_calc_outputs(package: ProjectPackage, segment_id: str) -> Optional[Segment]:
    """Efface uniquement les SORTIES du calcul (materiau/DN/classe/DI/DE/rugosite choisis par le
    moteur, debit/vitesse/PDC) sans toucher aux parametres hydrauliques SAISIS (debit de tete,
    niveaux amont, pressions, vitesse max) ni au statut 'force' — contrairement a
    `_reset_segment_to_default`, utilise quand le calcul lui-meme echoue pour ce troncon (alerte,
    cf. run_calculation) : les parametres saisis restent valides, seul le dimensionnement n'a pas
    abouti (consigne utilisateur : "ces paramètres ne doivent être remplis que lorsque le calcul
    aboutit sans erreur"). Un Materiau/DN force (consigne utilisateur) reste la contrainte de
    l'utilisateur, jamais effacee ici — l'affichage revient a CE pipeage (classe la moins chere
    disponible), pas au catalogue par defaut generique."""
    segment = package.segments.get(segment_id)
    if segment is None:
        return None
    if segment.forced_material is not None and segment.forced_dn is not None:
        try:
            selection = catalog.resolve_forced_selection(segment.forced_material, segment.forced_dn)
            default = {
                "material": selection["material"], "dn": selection["dn"],
                "pressure_class": selection["pressure_class"], "di": selection["di"], "de": selection["de"],
                "roughness": package.calculation_preferences.roughness_by_material.get(
                    selection["material"], catalog.default_roughness(selection["material"])
                ),
            }
        except catalog.CatalogLookupError:
            default = catalog.default_selection()
    else:
        default = catalog.default_selection()
    updated = segment.model_copy(
        update={
            "material": default["material"],
            "dn": default["dn"],
            "di": default["di"],
            "de": default["de"],
            "pressure_class": default["pressure_class"],
            "roughness": default["roughness"],
            "flow": 0.0,
            "velocity": None,
            "head_loss_unit": None,
            "head_loss_segment": None,
            "head_loss_cumulative": None,
            "segment_details": None,
        }
    )
    package.segments[segment_id] = updated
    return updated


def _segment_ids_touching_node(package: ProjectPackage, variant, trace_id: str, node_id: str, node_pk: float) -> set[str]:
    """Segments de TOUS les troncons de cette trace dont le PK du noeud tombe dans leur plage
    [pk_start, pk_end] (bornes incluses) — capture aussi bien un noeud qui demarre/termine un
    troncon (regime determine par son type) qu'un noeud transparent EN PLEIN MILIEU qui va devenir
    (ou cesser d'etre) une frontiere de troncon (fusion/scission, cf. BOUNDARY_NODE_TYPES) : dans
    tous ces cas, le(s) troncon(s) concerne(s) doi(ven)t perdre leur validation (consigne
    utilisateur : "réinitialiser les tronçons qui sont impactés")."""
    nodes = _nodes_for_variant(package, variant)
    trace_nodes = [n for n in nodes if str(n.trace_id) == trace_id]
    segments = _segments_for_variant(package, nodes)
    ordered = [(str(n.id), n.type, n.pk) for n in sorted(trace_nodes, key=lambda n: n.pk)]
    segment_by_edge = {(str(s.upstream_node_id), str(s.downstream_node_id)): str(s.id) for s in segments}
    ids: set[str] = set()
    for group in group_into_troncons(ordered, segment_by_edge):
        if group.pk_start - 1e-6 <= node_pk <= group.pk_end + 1e-6:
            ids.update(group.segment_ids)
    return ids


@router.post("/segments/{segment_id}/reset")
def reset_segment(session_id: str, variant_id: str, segment_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    segments = _segments_for_variant(package, nodes)
    segment = next((s for s in segments if str(s.id) == segment_id), None)
    if segment is None:
        raise HTTPException(status_code=404, detail="segment inconnu")

    updated = _reset_segment_to_default(package, segment_id)
    assert updated is not None
    return updated.model_dump(mode="json", exclude_none=True)


@router.put("/segments/{segment_id}/constraints")
def put_segment_constraints(
    session_id: str, variant_id: str, segment_id: str, payload: PutSegmentConstraintsRequest, request: Request
):
    """Panneau "Contraintes" de la fenêtre Tronçon (consigne utilisateur : matériau/DN/classe par
    PLAGE DE PK) — remplacement complet de la liste, comme "Préférences". Rejette (422) toute paire
    de contraintes dont les plages se croisent partiellement (ni imbrication ni disjonction) en
    renseignant différemment le même champ (cf. _find_contradictory_constraints). Invalide les
    sorties de calcul du tronçon (comme toute édition de "Modifier le tronçon") — un nouveau calcul
    est nécessaire pour que les contraintes s'appliquent."""
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    segments = _segments_for_variant(package, nodes)
    segment = next((s for s in segments if str(s.id) == segment_id), None)
    if segment is None:
        raise HTTPException(status_code=404, detail="segment inconnu")

    constraints = [
        SegmentConstraint(
            id=c.id or str(uuid.uuid4()), material=c.material, dn=c.dn, pressure_class=c.pressure_class,
            pk_start=c.pk_start, pk_end=c.pk_end, is_existing=c.is_existing, phase_id=c.phase_id, source=c.source,
        )
        for c in payload.constraints
    ]
    error = _find_contradictory_constraints(constraints, segment.pk_start, segment.pk_end)
    if error is not None:
        raise HTTPException(status_code=422, detail=error)

    updated = segment.model_copy(
        update={
            "constraints": constraints,
            "velocity": None,
            "head_loss_unit": None,
            "head_loss_segment": None,
            "head_loss_cumulative": None,
            "segment_details": None,
        }
    )
    package.segments[segment_id] = updated
    return updated.model_dump(mode="json", exclude_none=True)
