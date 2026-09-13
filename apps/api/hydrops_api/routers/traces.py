from __future__ import annotations

import asyncio
import math
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

import httpx

from hydropack.models import Crossing, ElevationProfile, LineStringGeometry, Node, Segment, TraceGeometry
from hydropack.serializer import ProjectPackage, TraceEntry

from hydrops_engine.topology import interpolate_lonlat_at_pk, sample_at_step, total_length_m

from ..core.deps import get_session_store, require_package
from ..core.import_job_store import ImportJobNotFoundError, ImportJobStore
from ..schemas import AddCrossingRequest, PatchCrossingRequest, PatchTraceRequest
from ..services import catalog
from ..services import crossings as crossings_service
from ..services.dem import DEFAULT_CHUNK_SIZE, DemProvider, DemProviderError
from ..services.kml_import import KmlImportError, extract_kml_bytes, parse_single_linestring
from ..services.profile_builder import DEFAULT_SAMPLE_STEP_M, build_elevation_profile

router = APIRouter(prefix="/projects/{session_id}", tags=["traces"])


def _import_job_store(request: Request) -> ImportJobStore:
    return request.app.state.import_job_store


async def _run_import_job(
    job_store: ImportJobStore,
    job_id: str,
    package: ProjectPackage,
    coordinates: list[tuple[float, float]],
    kml_bytes: bytes,
    source_label: str,
    dem_providers: list[DemProvider],
) -> None:
    """Tache de fond : le KML est deja valide (§ import_trace) — seul l'echantillonnage DEM,
    potentiellement long, reste a faire ici, avec progression rapportee via job_store."""

    def on_progress(completed: int, total: int) -> None:
        job_store.update_progress(job_id, completed, total)

    try:
        profile = await build_elevation_profile(coordinates, dem_providers, on_progress=on_progress)
    except DemProviderError as e:
        job_store.mark_failed(job_id, str(e))
        return
    except Exception as e:  # garde-fou : une tache de fond en echec ne doit jamais rester muette
        job_store.mark_failed(job_id, f"Erreur inattendue lors de l'import: {e}")
        return

    trace_id = uuid.uuid4()
    trace = TraceGeometry(
        id=trace_id,
        project_id=package.project.id,
        source=source_label,
        source_file_ref=f"traces/{trace_id}.source.kml",
        geometry=LineStringGeometry(type="LineString", coordinates=[list(c) for c in coordinates]),
        length=total_length_m(coordinates),
        water_type=package.project.default_water_type,
        elevation_profile=ElevationProfile(**profile),
    )
    package.traces[str(trace.id)] = TraceEntry(geometry=trace, source_kml_bytes=kml_bytes)
    # Le trace est partage au niveau projet — chaque variante existante obtient tout de suite son
    # propre reseau (2 noeuds terminal + 1 segment par defaut) sur ce nouveau trace.
    for variant_id in package.variants:
        seed_terminal_nodes_and_default_segment(package, trace, profile, uuid.UUID(variant_id))

    job_store.mark_done(job_id, trace.model_dump(mode="json", exclude_none=True))


def seed_terminal_nodes_and_default_segment(
    package: ProjectPackage, trace: TraceGeometry, profile: dict, variant_id: uuid.UUID
) -> None:
    """Une variante obtient tout de suite 2 noeuds aux extremites + 1 segment par defaut sur un
    trace donne — la table (§7) a donc un contenu reel sans action supplementaire de l'utilisateur.
    Type "junction" par defaut (pas "terminal"/Extremite, desormais interdit — consigne
    utilisateur) : une extremite est structurellement protegee par son PK
    (_is_structural_endpoint, routers/network.py), jamais par son type, qui peut et doit finir par
    porter un ouvrage reel (ex. une station de pompage en bout de trace). Le decoupage en
    plusieurs segments (jonctions/ouvrages) se fait ensuite via POST .../nodes (routers/network.py).
    Appele a l'import d'un trace (pour chaque variante existante) et a la creation d'une variante
    (pour chaque trace existant du projet, cf. routers/variants.py)."""
    coords = trace.geometry.coordinates
    raw_profile = profile.get("raw") or []
    z_start = raw_profile[0]["z"] if raw_profile else 0.0
    z_end = raw_profile[-1]["z"] if raw_profile else 0.0

    upstream = Node(
        id=uuid.uuid4(), trace_id=trace.id, variant_id=variant_id, type="junction", pk=0.0,
        x=coords[0][0], y=coords[0][1], z=z_start, z_source="dem",
    )
    downstream = Node(
        id=uuid.uuid4(), trace_id=trace.id, variant_id=variant_id, type="junction", pk=trace.length,
        x=coords[-1][0], y=coords[-1][1], z=z_end, z_source="dem",
    )
    default = catalog.default_selection()
    segment = Segment(
        id=uuid.uuid4(),
        upstream_node_id=upstream.id,
        downstream_node_id=downstream.id,
        pk_start=0.0,
        pk_end=trace.length,
        length=trace.length,
        material=default["material"],
        dn=default["dn"],
        di=default["di"],
        de=default["de"],
        pressure_class=default["pressure_class"],
        roughness=default["roughness"],
        flow=0.0,
        forced=False,
    )
    package.nodes[str(upstream.id)] = upstream
    package.nodes[str(downstream.id)] = downstream
    package.segments[str(segment.id)] = segment


@router.post("/traces/import", status_code=202)
async def import_trace(session_id: str, request: Request, file: UploadFile = File(...)):
    """Demarre l'import en tache de fond et retourne immediatement un job_id — l'echantillonnage
    DEM peut prendre plus d'une minute sur une trace longue (cas reel : 68 km, 4659 points).
    Suivre l'avancement via GET .../traces/import-jobs/{job_id}. Le KML/KMZ est valide de facon
    synchrone ci-dessous (rapide, pas besoin d'un job pour une erreur de format immediate).
    Le trace est cree au niveau projet (partage entre variantes) — plus besoin de variant_id."""
    package = require_package(get_session_store(request), session_id)

    content = await file.read()
    filename = file.filename or "trace.kml"
    try:
        kml_bytes = extract_kml_bytes(filename, content)
        coordinates = parse_single_linestring(kml_bytes)
    except KmlImportError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    total_chunks = math.ceil(len(sample_at_step(coordinates, DEFAULT_SAMPLE_STEP_M)) / DEFAULT_CHUNK_SIZE)

    job_store = _import_job_store(request)
    job = job_store.create(session_id, total_chunks=total_chunks)

    source_label = "kmz_import" if filename.lower().endswith(".kmz") else "kml_import"
    task = asyncio.create_task(
        _run_import_job(
            job_store, job.id, package, coordinates, kml_bytes, source_label, request.app.state.dem_providers
        )
    )
    job_store.track_task(task)

    return {"job_id": job.id, "total_chunks": total_chunks}


@router.get("/traces")
def list_traces(session_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    return [e.geometry.model_dump(mode="json", exclude_none=True) for e in package.traces.values()]


@router.get("/traces/import-jobs/{job_id}")
def get_import_job(session_id: str, job_id: str, request: Request):
    job_store = _import_job_store(request)
    try:
        job = job_store.get(job_id)
    except ImportJobNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if job.session_id != session_id:
        raise HTTPException(status_code=404, detail="job d'import inconnu pour cette session")
    return {
        "job_id": job.id,
        "status": job.status,
        "completed_chunks": job.completed_chunks,
        "total_chunks": job.total_chunks,
        "trace": job.trace,
        "error": job.error,
    }


@router.get("/traces/{trace_id}")
def get_trace(session_id: str, trace_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    entry = package.traces.get(trace_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")
    return entry.geometry.model_dump(mode="json", exclude_none=True)


@router.patch("/traces/{trace_id}")
def patch_trace(session_id: str, trace_id: str, payload: PatchTraceRequest, request: Request):
    package = require_package(get_session_store(request), session_id)
    entry = package.traces.get(trace_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")
    updates = payload.model_dump(exclude_none=True)
    if updates:
        entry.geometry = entry.geometry.model_copy(update=updates)
    return entry.geometry.model_dump(mode="json", exclude_none=True)


@router.post("/traces/{trace_id}/crossings")
def add_crossing(session_id: str, trace_id: str, payload: AddCrossingRequest, request: Request):
    """Ajout manuel d'une traversee depuis la carte (consigne utilisateur) — lon/lat projetes sur
    la geometrie de la trace au PK donne, jamais saisis directement. `source="manual"` : ne sera
    jamais ecrasee par une redetection Overpass ulterieure (cf. detect_crossings)."""
    package = require_package(get_session_store(request), session_id)
    entry = package.traces.get(trace_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")
    coordinates = [(c[0], c[1]) for c in entry.geometry.geometry.coordinates]
    lon, lat = interpolate_lonlat_at_pk(coordinates, payload.pk)
    new_crossing = Crossing(
        id=str(uuid.uuid4()), kind=payload.kind, label=payload.label, pk=payload.pk, lon=lon, lat=lat, source="manual"
    )
    entry.geometry = entry.geometry.model_copy(
        update={"crossings": [*(entry.geometry.crossings or []), new_crossing]}
    )
    return entry.geometry.model_dump(mode="json", exclude_none=True)


@router.patch("/traces/{trace_id}/crossings/{crossing_id}")
def patch_crossing(session_id: str, trace_id: str, crossing_id: str, payload: PatchCrossingRequest, request: Request):
    package = require_package(get_session_store(request), session_id)
    entry = package.traces.get(trace_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")
    existing = entry.geometry.crossings or []
    crossing = next((c for c in existing if c.id == crossing_id), None)
    if crossing is None:
        raise HTTPException(status_code=404, detail="traversée inconnue")
    updates = payload.model_dump(exclude_none=True)
    if "pk" in updates:
        coordinates = [(c[0], c[1]) for c in entry.geometry.geometry.coordinates]
        lon, lat = interpolate_lonlat_at_pk(coordinates, updates["pk"])
        updates["lon"], updates["lat"] = lon, lat
    updated_crossing = crossing.model_copy(update=updates)
    entry.geometry = entry.geometry.model_copy(
        update={"crossings": [updated_crossing if c.id == crossing_id else c for c in existing]}
    )
    return entry.geometry.model_dump(mode="json", exclude_none=True)


@router.delete("/traces/{trace_id}/crossings/{crossing_id}")
def delete_crossing(session_id: str, trace_id: str, crossing_id: str, request: Request):
    package = require_package(get_session_store(request), session_id)
    entry = package.traces.get(trace_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")
    existing = entry.geometry.crossings or []
    if not any(c.id == crossing_id for c in existing):
        raise HTTPException(status_code=404, detail="traversée inconnue")
    entry.geometry = entry.geometry.model_copy(update={"crossings": [c for c in existing if c.id != crossing_id]})
    return entry.geometry.model_dump(mode="json", exclude_none=True)


@router.post("/traces/{trace_id}/crossings/detect")
async def detect_crossings(session_id: str, trace_id: str, request: Request):
    """Detection des traversees (routes/rail/pistes, canaux/rivieres, bâtiments) — consigne
    utilisateur : "afficher et masquer". Declenchee a la demande (jamais automatiquement, cf.
    hydrops_api.services.crossings) : interroge Overpass (OpenStreetMap), calcule les points de
    croisement, et les met en cache sur la trace (evite de re-interroger Overpass a chaque
    ouverture du projet)."""
    package = require_package(get_session_store(request), session_id)
    entry = package.traces.get(trace_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")
    coordinates = [(c[0], c[1]) for c in entry.geometry.geometry.coordinates]
    bbox = crossings_service.trace_bbox(coordinates)
    try:
        features = await crossings_service.fetch_osm_features(bbox)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Service de traversées (Overpass/OSM) indisponible : {e}") from e
    found = crossings_service.compute_crossings(coordinates, features)
    # Les traversees ajoutees/modifiees manuellement depuis la carte (consigne utilisateur) ne
    # sont jamais ecrasees par une redetection — conservees telles quelles, la detection ne
    # remplace que celles qu'elle a elle-meme produites ("source" == "detected").
    manual = [c for c in (entry.geometry.crossings or []) if c.source == "manual"]
    entry.geometry = entry.geometry.model_copy(
        update={
            "crossings": [
                Crossing(id=c.id, kind=c.kind, label=c.label, subtype=c.subtype, pk=c.pk, lon=c.lon, lat=c.lat)
                for c in found
            ]
            + manual
        }
    )
    return entry.geometry.model_dump(mode="json", exclude_none=True)


@router.delete("/traces/{trace_id}", status_code=204)
def delete_trace(session_id: str, trace_id: str, request: Request):
    """Un trace est partage entre variantes : sa suppression retire aussi tous les noeuds/segments
    que CHAQUE variante avait construits dessus (cascade toutes variantes confondues)."""
    package = require_package(get_session_store(request), session_id)
    entry = package.traces.pop(trace_id, None)
    if entry is None:
        raise HTTPException(status_code=404, detail="trace inconnue")

    orphan_node_ids = {nid for nid, n in package.nodes.items() if str(n.trace_id) == trace_id}
    for nid in orphan_node_ids:
        del package.nodes[nid]
    orphan_segment_ids = {
        sid for sid, s in package.segments.items()
        if str(s.upstream_node_id) in orphan_node_ids or str(s.downstream_node_id) in orphan_node_ids
    }
    for sid in orphan_segment_ids:
        del package.segments[sid]
