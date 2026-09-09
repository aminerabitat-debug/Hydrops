"""Noeuds et segments (cdc §5.2, §7, §8, §10) — Lot 3 etape 1/1b.

Perimetre volontairement restreint : types de noeud `terminal` (auto, extremites de trace),
`junction` (decoupe un segment en deux sans etre un ouvrage), `tie_in`/`reservoir`/
`pumping_station`/`pressure_break`/`treatment_plant` (ouvrages "legers", taggage du type
seulement — la mise en donnees detaillee par ouvrage, cdc §8, arrive plus tard). Points hauts/bas
et vannes restent exclus (consigne utilisateur). Le calcul hydraulique arrive a l'etape suivante.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from hydropack.models import Node, Segment
from hydropack.serializer import ProjectPackage

from hydrops_engine.topology import (
    group_into_troncons,
    interpolate_lonlat_at_pk,
    interpolate_value_at_pk,
    validate_non_increasing_di,
    validate_pk_strictly_increasing,
)

from ..core.deps import get_session_store, require_package
from ..schemas import NewNodeRequest, PatchNodeRequest, PatchSegmentRequest
from ..services import catalog

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


def _is_structural_endpoint(package: ProjectPackage, node: Node) -> bool:
    """Un noeud est une extremite STRUCTURELLE de trace (indeletable, meme s'il porte desormais un
    ouvrage — consigne utilisateur, Lot 3 etape 1c) si son PK correspond a 0 ou a la longueur de sa
    trace — independant de son `type`, qui peut changer (ex. terminal -> reservoir)."""
    trace_entry = package.traces.get(str(node.trace_id))
    if trace_entry is None:
        return False
    trace = trace_entry.geometry
    return node.pk <= _ENDPOINT_PK_TOLERANCE_M or node.pk >= trace.length - _ENDPOINT_PK_TOLERANCE_M


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
    )
    package.nodes[str(node.id)] = node

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
        forced=enclosing.forced,
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
        forced=enclosing.forced,
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
    if not updates:
        return node.model_dump(mode="json", exclude_none=True)

    updated = node.model_copy(update=updates)
    package.nodes[node_id] = updated
    return updated.model_dump(mode="json", exclude_none=True)


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

    material = payload.material or segment.material
    pressure_class = payload.pressure_class or segment.pressure_class
    dn = payload.dn if payload.dn is not None else segment.dn

    try:
        resolved = catalog.resolve(material, dn, pressure_class)
    except catalog.CatalogLookupError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # "force" marque desormais simplement "les donnees de ce troncon ont ete validees via la
    # fenetre Modifier" (consigne utilisateur : couleur du texte une fois valide/reinitialise) —
    # pas seulement un ecart par rapport au catalogue par defaut.
    updates: dict = {
        "material": material,
        "dn": dn,
        "pressure_class": pressure_class,
        "di": resolved["di"],
        "de": resolved["de"],
        "roughness": resolved["roughness"],
        "forced": True,
    }
    if payload.upstream_water_level_max is not None:
        updates["upstream_water_level_max"] = payload.upstream_water_level_max
    if payload.upstream_water_level_min is not None:
        updates["upstream_water_level_min"] = payload.upstream_water_level_min
    if payload.min_pressure is not None:
        updates["min_pressure"] = payload.min_pressure
    if payload.downstream_residual_pressure is not None:
        updates["downstream_residual_pressure"] = payload.downstream_residual_pressure
    if payload.max_velocity is not None:
        updates["max_velocity"] = payload.max_velocity

    updated = segment.model_copy(update=updates)
    package.segments[segment_id] = updated
    return updated.model_dump(mode="json", exclude_none=True)


@router.post("/segments/{segment_id}/reset")
def reset_segment(session_id: str, variant_id: str, segment_id: str, request: Request):
    """Reinitialise un segment aux valeurs catalogue par defaut (materiau/DN/classe), et efface son
    statut 'force' — equivalent d'une "suppression" de la mise en donnees d'un troncon (consigne
    utilisateur) sans toucher a la topologie (noeuds/segments restent en place, seules leurs
    caracteristiques hydrauliques reviennent au defaut pose a l'import)."""
    package = require_package(get_session_store(request), session_id)
    variant = _require_variant(package, variant_id)
    nodes = _nodes_for_variant(package, variant)
    segments = _segments_for_variant(package, nodes)
    segment = next((s for s in segments if str(s.id) == segment_id), None)
    if segment is None:
        raise HTTPException(status_code=404, detail="segment inconnu")

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
            "upstream_water_level_max": None,
            "upstream_water_level_min": None,
            "min_pressure": None,
            "downstream_residual_pressure": None,
            "max_velocity": None,
        }
    )
    package.segments[segment_id] = updated
    return updated.model_dump(mode="json", exclude_none=True)
