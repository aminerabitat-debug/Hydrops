from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from pydantic import ValidationError

from hydropack.models import (
    AnnualVolumeConstant,
    AnnualVolumePoint,
    AnnualVolumeTable,
    LifetimesByCategory,
    Metadata,
    Project,
    TechnoEconomicAssumptions,
    Variant,
)
from hydropack.serializer import ProjectPackage, pack, unpack
from hydropack.validation import HydropackValidationError

from ..core.config import get_settings
from ..core.deps import get_session_store, require_package, require_session
from ..schemas import NewProjectRequest, PatchProjectRequest, ProjectFormFields

router = APIRouter(prefix="/projects", tags=["projects"])


def _project_response(package: ProjectPackage) -> dict:
    return {
        "metadata": package.metadata.model_dump(mode="json", exclude_none=True),
        "project": package.project.model_dump(mode="json", exclude_none=True),
        "variants": [v.model_dump(mode="json", exclude_none=True) for v in package.variants.values()],
        "traces": [e.geometry.model_dump(mode="json", exclude_none=True) for e in package.traces.values()],
    }


def _build_annual_volume(payload: ProjectFormFields) -> AnnualVolumeConstant | AnnualVolumeTable:
    if payload.annual_volume_points:
        return AnnualVolumeTable(
            mode="table",
            points=[AnnualVolumePoint(year=p.year, value=p.value) for p in payload.annual_volume_points],
        )
    return AnnualVolumeConstant(mode="constant", value=payload.annual_volume_value)


def _apply_project_form_fields(existing: Project | None, project_id: uuid.UUID, payload: ProjectFormFields) -> Project:
    """Construit/remplace les champs du formulaire "Parametres du projet" — cree (existing=None) ou
    edite (existing fourni, ses champs hors formulaire — description, branding, langue... — sont
    preserves) un Project. model_validate (pas model_copy) pour revalider les contraintes."""
    base = existing.model_dump(mode="json") if existing else {}
    base.update(
        {
            "id": str(project_id),
            "name": payload.name,
            "client": payload.client,
            "currency": payload.currency,
            "default_water_type": payload.default_water_type,
            "study_horizon_years": payload.study_horizon_years,
            "project_lifetime_years": payload.project_lifetime_years,
            "first_investment_year": payload.first_investment_year,
            "commissioning_year": payload.commissioning_year,
            "amortization_years": payload.amortization_years,
            "discount_rate": payload.discount_rate,
            "energy_price": payload.energy_price,
            "annual_volume": _build_annual_volume(payload).model_dump(mode="json"),
            "lifetimes_by_category": LifetimesByCategory(
                pipes=payload.lifetimes_pipes,
                civil_works=payload.lifetimes_civil_works,
                electromechanical=payload.lifetimes_electromechanical,
                instrumentation_control=payload.lifetimes_instrumentation_control,
                other=payload.lifetimes_other,
            ).model_dump(mode="json"),
        }
    )
    return Project.model_validate(base)


@router.post("/new")
def new_project(session_id: str, payload: NewProjectRequest, request: Request):
    store = get_session_store(request)
    require_session(store, session_id)

    now = datetime.now(timezone.utc)
    project = _apply_project_form_fields(None, uuid.uuid4(), payload)
    metadata = Metadata(software_version=get_settings().software_version, created_at=now, modified_at=now)

    # Une variante par defaut est creee immediatement : le parcours Lot 1 (creer projet -> importer
    # KML) n'oblige pas l'utilisateur a un appel explicite "creer variante" avant le premier import.
    default_variant = Variant(id=uuid.uuid4(), project_id=project.id, name="Variante 1")

    package = ProjectPackage(
        metadata=metadata,
        project=project,
        techno_economic=TechnoEconomicAssumptions(),
        variants={str(default_variant.id): default_variant},
    )
    store.set_package(session_id, package)
    return _project_response(package)


@router.get("/{session_id}")
def get_project(session_id: str, request: Request):
    store = get_session_store(request)
    package = require_package(store, session_id)
    return _project_response(package)


@router.patch("/{session_id}")
def patch_project(session_id: str, payload: PatchProjectRequest, request: Request):
    """Edition depuis "Parametres du projet" — meme formulaire complet que la creation, pas un
    patch partiel champ par champ (cf. ProjectFormFields)."""
    store = get_session_store(request)
    package = require_package(store, session_id)
    now = datetime.now(timezone.utc)
    try:
        package.project = _apply_project_form_fields(package.project, package.project.id, payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    package.metadata = package.metadata.model_copy(update={"modified_at": now})
    return _project_response(package)


@router.post("/import")
async def import_project(session_id: str, request: Request, file: UploadFile = File(...)):
    store = get_session_store(request)
    require_session(store, session_id)
    content = await file.read()
    try:
        package = unpack(content)
    except HydropackValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # zip corrompu, json illisible, etc.
        raise HTTPException(status_code=422, detail=f"Fichier .hydrops illisible: {e}") from e
    store.set_package(session_id, package)
    return _project_response(package)


@router.get("/{session_id}/export")
def export_project(session_id: str, request: Request):
    store = get_session_store(request)
    package = require_package(store, session_id)
    package.metadata = package.metadata.model_copy(update={"modified_at": datetime.now(timezone.utc)})
    data = pack(package)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", package.project.name).strip("_") or "projet"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.hydrops"'},
    )
