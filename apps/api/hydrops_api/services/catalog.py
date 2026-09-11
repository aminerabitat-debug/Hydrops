"""Catalogue technique "Conduites" (menu Base de données > Conduites, consigne utilisateur) —
Lot 3 etape 2 (calcul + base de donnees). Remplace le jeu SDR/K synthetique de l'etape precedente
par le jeu de test fourni par l'utilisateur (327 lignes, cf. data/pipe_catalog_seed.py) :
une ligne = une combinaison (DN, materiau, classe de pression) avec DI, PMS (pression maximale de
service, mCE) et prix. Base preliminaire pour les tests, a mettre a jour plus tard (consigne
utilisateur) — reste en memoire, comme le reste de l'etat de session (pas de Postgres, decision
utilisateur anterieure).

`active` (colonne "Actif" de la fenetre Conduites) exclut une ligne des recherches du moteur de
calcul sans la supprimer : certains DN ne sont pas toujours standards selon les cas (consigne
utilisateur). La rugosite n'est plus portee par le catalogue mais par les Preferences de calcul
(par materiau, cf. services/preferences.py) — un materiau peut apparaitre dans plusieurs lignes
(DN/classe) du catalogue avec toujours la MEME rugosite.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.pipe_catalog_seed import DEFAULT_ROUGHNESS_MM, MATERIAL_LABELS, PIPE_CATALOG_SEED


@dataclass
class PipeCatalogRow:
    id: int
    dn: int
    di: float
    material: str
    pressure_class: str
    pms: float
    prix_ftp: float
    prix_fourniture: float
    prix_aps: float
    active: bool = True


_CATALOG: dict[int, PipeCatalogRow] = {
    row[0]: PipeCatalogRow(
        id=row[0], dn=row[1], di=row[2], material=row[3], pressure_class=row[4],
        pms=row[5], prix_ftp=row[6], prix_fourniture=row[7], prix_aps=row[8], active=True,
    )
    for row in PIPE_CATALOG_SEED
}


class CatalogLookupError(ValueError):
    pass


def list_pipe_rows() -> list[PipeCatalogRow]:
    return sorted(_CATALOG.values(), key=lambda r: r.id)


def list_active_pipe_rows() -> list[PipeCatalogRow]:
    return [r for r in list_pipe_rows() if r.active]


def set_row_active(row_id: int, active: bool) -> PipeCatalogRow:
    row = _CATALOG.get(row_id)
    if row is None:
        raise CatalogLookupError(f"ligne catalogue inconnue: {row_id}")
    row.active = active
    return row


def list_materials() -> list[dict]:
    """Materiaux distincts presents dans le catalogue (actifs ou non — la fenetre Conduites doit
    pouvoir reactiver une ligne desactivee du seul materiau restant)."""
    seen: dict[str, str] = {}
    for row in list_pipe_rows():
        seen.setdefault(row.material, MATERIAL_LABELS.get(row.material, row.material))
    return [{"material": m, "label": label} for m, label in seen.items()]


def list_pressure_classes(material: str) -> list[str]:
    classes = sorted({r.pressure_class for r in _CATALOG.values() if r.material == material})
    if not classes:
        raise CatalogLookupError(f"materiau inconnu: {material}")
    return classes


def list_diameters(material: str, pressure_class: str) -> list[dict]:
    rows = [r for r in _CATALOG.values() if r.material == material and r.pressure_class == pressure_class]
    if not rows:
        raise CatalogLookupError(f"combinaison materiau/classe inconnue: {material}/{pressure_class}")
    return sorted(({"dn": r.dn, "di": r.di, "de": float(r.dn)} for r in rows), key=lambda d: d["dn"])


def resolve(material: str, dn: int, pressure_class: str) -> dict:
    """Retourne {di, de} (mm) pour (materiau, DN, classe), ou leve CatalogLookupError si la
    combinaison n'existe pas dans le catalogue — jamais une valeur devinee silencieusement. La
    rugosite n'est plus resolue ici (cf. services/preferences.py:roughness_for_material)."""
    for row in _CATALOG.values():
        if row.material == material and row.dn == dn and row.pressure_class == pressure_class:
            return {"di": row.di, "de": float(row.dn)}
    raise CatalogLookupError(f"DN {dn} indisponible pour {material}/{pressure_class}")


def material_dn_exists(material: str, dn: int) -> bool:
    """Existe-t-il au moins une ligne ACTIVE (materiau, DN), quelle que soit la classe de pression
    — utilise pour valider un DN "force" (fenetre Modifier le tronçon, consigne utilisateur :
    contraindre Materiau/DN sans imposer une classe precise, cf. resolve_forced_selection qui
    choisit la classe la moins chere satisfaisant le PMS requis)."""
    return any(r.active and r.material == material and r.dn == dn for r in _CATALOG.values())


def resolve_forced_selection(material: str, dn: int, min_pms_m: float = 0.0) -> dict:
    """Pour un (materiau, DN) force (pas de classe imposee) : retient la classe de pression la
    moins chere parmi les lignes actives qui respectent `min_pms_m`, ou a defaut (aucune ne le
    respecte) la moins chere tout court — jamais un echec silencieux, l'appelant doit alerter si
    `pms_ok` est faux. Leve CatalogLookupError si la combinaison n'existe meme pas (devrait avoir
    ete ecartee a la saisie, cf. material_dn_exists)."""
    matches = [r for r in _CATALOG.values() if r.active and r.material == material and r.dn == dn]
    if not matches:
        raise CatalogLookupError(f"aucune conduite active {material} DN{dn}")
    meeting_pms = [r for r in matches if r.pms >= min_pms_m - 1e-9]
    pool = meeting_pms or matches
    row = min(pool, key=lambda r: (r.prix_aps, r.pressure_class))
    return {
        "material": row.material, "dn": row.dn, "pressure_class": row.pressure_class,
        "di": row.di, "de": float(row.dn), "pms": row.pms, "pms_ok": bool(meeting_pms),
    }


def default_roughness(material: str) -> float:
    return DEFAULT_ROUGHNESS_MM.get(material, 0.1)


def default_selection() -> dict:
    """Selection par defaut appliquee aux nouveaux segments auto-crees a l'import d'une trace —
    PEHD PN10 DN160, un choix de depart courant en adduction d'eau, pas un dimensionnement."""
    material, pressure_class, dn = "PEHD", "PN10", 160
    resolved = resolve(material, dn, pressure_class)
    return {"material": material, "pressure_class": pressure_class, "dn": dn, "roughness": default_roughness(material), **resolved}
