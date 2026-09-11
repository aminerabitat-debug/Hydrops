from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..schemas import PatchCatalogRowRequest
from ..services import catalog

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/materials")
def list_materials():
    return catalog.list_materials()


@router.get("/pressure-classes")
def list_pressure_classes(material: str):
    try:
        return catalog.list_pressure_classes(material)
    except catalog.CatalogLookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/diameters")
def list_diameters(material: str, pressure_class: str):
    try:
        return catalog.list_diameters(material, pressure_class)
    except catalog.CatalogLookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _row_dict(row: catalog.PipeCatalogRow) -> dict:
    return {
        "id": row.id, "dn": row.dn, "di": row.di, "material": row.material,
        "pressure_class": row.pressure_class, "pms": row.pms, "prix_ftp": row.prix_ftp,
        "prix_fourniture": row.prix_fourniture, "prix_aps": row.prix_aps, "active": row.active,
    }


@router.get("/conduites")
def list_conduites():
    """Base "Conduites" (menu Base de données > Conduites, consigne utilisateur) — jeu
    préliminaire de test, toutes les lignes (actives ou non) : la fenêtre Conduites doit pouvoir
    décocher/recocher "Actif" sur chacune sans la faire disparaître de la liste."""
    return [_row_dict(r) for r in catalog.list_pipe_rows()]


@router.patch("/conduites/{row_id}")
def patch_conduite(row_id: int, payload: PatchCatalogRowRequest):
    try:
        row = catalog.set_row_active(row_id, payload.active)
    except catalog.CatalogLookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _row_dict(row)
