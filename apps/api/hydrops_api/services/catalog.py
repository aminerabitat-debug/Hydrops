"""Catalogue technique statique (cdc §15) — Lot 3 etape 1.

docs/architecture/03-modele-donnees.md §3.11 place le catalogue (diametres, materiaux, classes de
pression, rugosites) dans un schema Postgres durable, distinct de la session ephemere. Standing up
Postgres avant meme d'avoir un calcul hydraulique qui marche a ete ecarte pour cette etape
(decision utilisateur) : ce module fournit un jeu de reference statique, en memoire, qui remplit
le meme contrat (`resolve(material, dn, pressure_class) -> {di, de, roughness}`) — migrable vers
une vraie table Postgres plus tard sans changer les endpoints `/catalog/*` qui l'exposent.

Valeurs derivees des formules SDR/K normalisees usuelles (ISO 4427 PE, EN 1452 PVC, ISO 2531 fonte
ductile K9) pour un jeu de DN commerciaux courants — un point de depart editable (cdc §15 : "toutes
les valeurs doivent rester tracables et editables"), pas une verite d'ingenierie figee.

Unites : DN/DI/DE en millimetres, rugosite (k, aspérité absolue) en millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiameterEntry:
    dn: int
    di: float
    de: float


@dataclass(frozen=True)
class MaterialSpec:
    material: str
    label: str
    roughness_mm: float
    pressure_classes: dict[str, float]  # pressure_class -> SDR (plastiques) ou classe K (fonte)


# SDR (Standard Dimension Ratio) : paroi e = DE / SDR, donc DI = DE * (1 - 2/SDR).
_MATERIALS: dict[str, MaterialSpec] = {
    "pehd_pe100": MaterialSpec(
        material="pehd_pe100",
        label="PEHD PE100",
        roughness_mm=0.01,
        pressure_classes={"pn10": 17.0, "pn16": 11.0},
    ),
    "pvc": MaterialSpec(
        material="pvc",
        label="PVC-U",
        roughness_mm=0.01,
        pressure_classes={"pn10": 21.0, "pn16": 13.6},
    ),
}

_PLASTIC_DE_MM = [63, 75, 90, 110, 125, 140, 160, 180, 200, 225, 250, 280, 315, 355, 400, 450, 500]

# Fonte ductile K9 (ISO 2531) : e(mm) = 9 * (0.5 + 0.001*DN) ; DE standard approx. par DN.
_DUCTILE_IRON_DE_BY_DN_MM: dict[int, float] = {
    100: 118, 125: 144, 150: 170, 200: 222, 250: 274,
    300: 326, 350: 378, 400: 429, 500: 532, 600: 635,
}


def _plastic_diameters(sdr: float) -> list[DiameterEntry]:
    return [DiameterEntry(dn=de, di=round(de * (1 - 2 / sdr), 1), de=float(de)) for de in _PLASTIC_DE_MM]


def _ductile_iron_diameters() -> list[DiameterEntry]:
    entries = []
    for dn, de in _DUCTILE_IRON_DE_BY_DN_MM.items():
        e = 9 * (0.5 + 0.001 * dn)
        entries.append(DiameterEntry(dn=dn, di=round(de - 2 * e, 1), de=float(de)))
    return entries


_FONTE_DUCTILE = MaterialSpec(
    material="fonte_ductile",
    label="Fonte ductile K9",
    roughness_mm=0.1,
    pressure_classes={"k9": 9.0},
)
_MATERIALS[_FONTE_DUCTILE.material] = _FONTE_DUCTILE

_DIAMETERS: dict[tuple[str, str], list[DiameterEntry]] = {
    ("pehd_pe100", "pn10"): _plastic_diameters(_MATERIALS["pehd_pe100"].pressure_classes["pn10"]),
    ("pehd_pe100", "pn16"): _plastic_diameters(_MATERIALS["pehd_pe100"].pressure_classes["pn16"]),
    ("pvc", "pn10"): _plastic_diameters(_MATERIALS["pvc"].pressure_classes["pn10"]),
    ("pvc", "pn16"): _plastic_diameters(_MATERIALS["pvc"].pressure_classes["pn16"]),
    ("fonte_ductile", "k9"): _ductile_iron_diameters(),
}


class CatalogLookupError(ValueError):
    pass


def list_materials() -> list[MaterialSpec]:
    return list(_MATERIALS.values())


def list_pressure_classes(material: str) -> list[str]:
    spec = _MATERIALS.get(material)
    if spec is None:
        raise CatalogLookupError(f"materiau inconnu: {material}")
    return list(spec.pressure_classes.keys())


def list_diameters(material: str, pressure_class: str) -> list[DiameterEntry]:
    key = (material, pressure_class)
    if key not in _DIAMETERS:
        raise CatalogLookupError(f"combinaison materiau/classe inconnue: {material}/{pressure_class}")
    return _DIAMETERS[key]


def resolve(material: str, dn: int, pressure_class: str) -> dict:
    """Retourne {di, de, roughness} (mm) pour (materiau, DN, classe), ou leve CatalogLookupError
    si la combinaison n'existe pas dans le catalogue — jamais une valeur devinee silencieusement."""
    spec = _MATERIALS.get(material)
    if spec is None:
        raise CatalogLookupError(f"materiau inconnu: {material}")
    for entry in list_diameters(material, pressure_class):
        if entry.dn == dn:
            return {"di": entry.di, "de": entry.de, "roughness": spec.roughness_mm}
    raise CatalogLookupError(f"DN {dn} indisponible pour {material}/{pressure_class}")


def default_selection() -> dict:
    """Selection par defaut appliquee aux nouveaux segments auto-crees a l'import d'une trace —
    PEHD PE100 PN10 DN160, un choix de depart courant en adduction d'eau, pas un dimensionnement."""
    material, pressure_class, dn = "pehd_pe100", "pn10", 160
    resolved = resolve(material, dn, pressure_class)
    return {"material": material, "pressure_class": pressure_class, "dn": dn, **resolved}
