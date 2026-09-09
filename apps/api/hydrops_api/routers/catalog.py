from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services import catalog

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/materials")
def list_materials():
    return [
        {"material": m.material, "label": m.label, "pressure_classes": list(m.pressure_classes.keys())}
        for m in catalog.list_materials()
    ]


@router.get("/pressure-classes")
def list_pressure_classes(material: str):
    try:
        return catalog.list_pressure_classes(material)
    except catalog.CatalogLookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/diameters")
def list_diameters(material: str, pressure_class: str):
    try:
        entries = catalog.list_diameters(material, pressure_class)
    except catalog.CatalogLookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return [{"dn": e.dn, "di": e.di, "de": e.de} for e in entries]
