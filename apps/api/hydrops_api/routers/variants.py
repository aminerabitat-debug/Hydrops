from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from pydantic import ValidationError

from hydropack.models import Variant
from hydropack.serializer import ProjectPackage

from ..core.deps import get_session_store, require_package
from ..schemas import NewVariantRequest, PatchVariantRequest
from .traces import seed_terminal_nodes_and_default_segment

router = APIRouter(prefix="/projects/{session_id}/variants", tags=["variants"])


def _unique_duplicate_name(package: ProjectPackage, original_name: str) -> str:
    """Genere un nom de copie non redondant (consigne utilisateur) : "<nom> (copie)", puis
    "(copie 2)", "(copie 3)"... si necessaire, jusqu'a trouver un nom absent des variantes
    existantes du projet."""
    existing = {v.name for v in package.variants.values()}
    candidate = f"{original_name} (copie)"
    if candidate not in existing:
        return candidate
    n = 2
    while f"{original_name} (copie {n})" in existing:
        n += 1
    return f"{original_name} (copie {n})"


@router.get("")
def list_variants(session_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    return [v.model_dump(mode="json", exclude_none=True) for v in package.variants.values()]


@router.post("")
def create_variant(session_id: str, payload: NewVariantRequest, request: Request):
    package = require_package(get_session_store(request), session_id)
    variant = Variant(
        id=uuid.uuid4(), project_id=package.project.id, name=payload.name, description=payload.description
    )
    package.variants[str(variant.id)] = variant

    # Les traces sont partagees au niveau projet — une nouvelle variante recoit tout de suite son
    # propre reseau (2 noeuds terminal + 1 segment par defaut) sur chaque trace deja importe.
    for entry in package.traces.values():
        profile_dict = entry.geometry.elevation_profile.model_dump(mode="json") if entry.geometry.elevation_profile else {}
        seed_terminal_nodes_and_default_segment(package, entry.geometry, profile_dict, variant.id)

    return variant.model_dump(mode="json", exclude_none=True)


@router.post("/{variant_id}/duplicate")
def duplicate_variant(session_id: str, variant_id: str, request: Request):
    """Duplication integrale (V1-03) : copie le reseau noeuds/segments propre a la variante, avec
    de nouveaux ids — jamais une reference partagee. Les traces restent communes au projet, donc
    ne sont pas dupliquees."""
    package = require_package(get_session_store(request), session_id)
    original = package.variants.get(variant_id)
    if original is None:
        raise HTTPException(status_code=404, detail="variante inconnue")
    copy = original.model_copy(
        update={
            "id": uuid.uuid4(),
            "duplicated_from_variant_id": original.id,
            "name": _unique_duplicate_name(package, original.name),
        }
    )
    package.variants[str(copy.id)] = copy

    original_nodes = [n for n in package.nodes.values() if str(n.variant_id) == variant_id]
    id_map: dict[str, uuid.UUID] = {}
    for node in original_nodes:
        new_id = uuid.uuid4()
        id_map[str(node.id)] = new_id
        package.nodes[str(new_id)] = node.model_copy(update={"id": new_id, "variant_id": copy.id})

    original_segments = [s for s in package.segments.values() if str(s.upstream_node_id) in id_map]
    for segment in original_segments:
        new_id = uuid.uuid4()
        package.segments[str(new_id)] = segment.model_copy(
            update={
                "id": new_id,
                "upstream_node_id": id_map[str(segment.upstream_node_id)],
                "downstream_node_id": id_map[str(segment.downstream_node_id)],
            }
        )

    return copy.model_dump(mode="json", exclude_none=True)


@router.patch("/{variant_id}")
def patch_variant(session_id: str, variant_id: str, payload: PatchVariantRequest, request: Request):
    package = require_package(get_session_store(request), session_id)
    variant = package.variants.get(variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="variante inconnue")
    updates = payload.model_dump(exclude_none=True)
    if updates:
        merged = {**variant.model_dump(mode="json"), **updates}
        try:
            variant = Variant.model_validate(merged)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        package.variants[variant_id] = variant
    return variant.model_dump(mode="json", exclude_none=True)


@router.delete("/{variant_id}", status_code=204)
def delete_variant(session_id: str, variant_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    if package.variants.pop(variant_id, None) is None:
        raise HTTPException(status_code=404, detail="variante inconnue")

    orphan_node_ids = {nid for nid, n in package.nodes.items() if str(n.variant_id) == variant_id}
    for nid in orphan_node_ids:
        del package.nodes[nid]
    orphan_segment_ids = {
        sid for sid, s in package.segments.items()
        if str(s.upstream_node_id) in orphan_node_ids or str(s.downstream_node_id) in orphan_node_ids
    }
    for sid in orphan_segment_ids:
        del package.segments[sid]
