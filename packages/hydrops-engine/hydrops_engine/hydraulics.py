"""Moteur de calcul hydraulique (bouton Calcul > Calculer, consigne utilisateur) — Lot 3 etape 2.

Fonctions pures operant sur des dataclasses simples, sans dependance a hydropack/FastAPI (meme
principe que topology/network.py : "moteur pur, sans effet de bord", l'appelant cote API convertit
les modeles pydantic vers/depuis ces types avant/apres l'appel).

Approche retenue (2e iteration, validee avec l'utilisateur) — les deux regimes sont desormais
CALCULES EN SENS OPPOSE, parce que leur cote de depart n'a pas le meme statut physique :

  - Gravitaire : le niveau du reservoir amont est une donnee FIXE (la nature, pas un choix de
    conception) — on ne peut pas "l'augmenter" pour rattraper un manque de pression en route. On
    parcourt donc le troncon AVAL -> AMONT : en partant de la pression minimale/residuelle exigee
    au point le plus aval, on reconstruit en remontant (en ADDITIONNANT les pertes de charge) la
    cote qui serait necessaire en tete pour que cette exigence soit tenue. Cette cote "necessaire"
    est ensuite comparee au niveau REELLEMENT disponible (upstream_level_min) : s'il y a de la
    marge, tout le profil est translate vers le haut de cette marge (les DN choisis, donc les
    pertes de charge, ne changent pas) ; sinon, une ALERTE invite l'utilisateur a revoir le
    decoupage du trace (brise-charge, troncon plus court...) — on ne peut pas "forcer" un
    reservoir. Un controle final verifie, noeud par noeud, que la pression minimale exigee est
    effectivement tenue partout une fois la translation appliquee. Les cotes/pressions
    HYDROSTATIQUES (sans ecoulement) restent calculees separement, a niveau constant (max et min).
  - Refoulement : la pression de refoulement en tete N'EST PAS fixee par la nature — c'est un choix
    de conception (dimensionnement de la pompe), qui peut toujours etre "augmente" si besoin. On
    parcourt donc le troncon AMONT -> AVAL : les DN sont choisis uniquement sur la contrainte de
    vitesse (+ decroissance du DN vers l'aval), puis la PLUS PETITE cote de depart qui garantit la
    pression minimale/residuelle est calculee directement sous forme close (mathematiquement
    equivalente a "augmenter la cote de depart jusqu'a ce que ca marche partout", sans avoir besoin
    d'iterer) — EN TOUT point du profil de terrain echantillonne (`terrain_samples`), pas seulement
    aux noeuds reels (consigne utilisateur : "pas de message d'erreur, il faut augmenter la cote
    piezometrique du 1er piquet jusqu'a ce que ca se regle"). Pas de scenario hydrostatique en
    refoulement (consigne utilisateur).
  - Controle sur le PROFIL DE TERRAIN : un troncon peut n'avoir que 2 noeuds reels (ses deux
    extremites) mais couvrir plusieurs kilometres de terrain accidente entre les deux (releve
    GPS/DEM, cf. TraceGeometry.elevation_profile) — la ligne piezometrique, elle, varie LINEAIREMENT
    entre deux noeuds (perte de charge constante sur un segment a DN fixe), donc verifier la
    pression minimale aux seuls noeuds ne suffit pas : un point haut intermediaire du terrain
    (jamais materialise par un noeud) peut tres bien passer sous la ligne piezometrique sans
    qu'aucune des deux extremites ne le detecte. En GRAVITAIRE, la cote de depart (niveau du
    reservoir) est fixe : on ne peut que CONSTATER un defaut, une fois la ligne piezometrique finale
    connue (apres translation), contre CHAQUE point echantillonne du profil de terrain fourni par
    l'appelant (`terrain_samples`) — une seule alerte agregee (PK de debut/fin de la zone en defaut,
    pire cas), jamais un correctif automatique (le DN ne peut pas etre augmente sans revoir aussi le
    decoupage/emplacement des noeuds) : "revoir le decoupage du trace" s'applique dans ce cas. En
    REFOULEMENT, la cote de depart N'EST PAS fixe (cf. ci-dessus) : les points de terrain sont donc
    directement integres au calcul de H0 (aucune alerte pression necessaire) ; seul un depassement du
    PMS de la conduite retenue reste signale par alerte (la pression, elle, ne peut pas etre
    "silencieusement" acceptee au-dela de ce que la conduite supporte).
  - Choix DN/materiau/classe par segment : parmi les lignes ACTIVES du catalogue respectant la
    vitesse max ET min (Preferences, consigne utilisateur — defaut 0.2 m/s, cf.
    max_di_mm_for_velocity), la contrainte de decroissance du DN vers l'aval (en gravitaire, le DN
    choisi en remontant ne peut jamais etre INFERIEUR a celui du segment deja fixe plus a l'aval —
    en refoulement, en descendant, il ne peut jamais DEPASSER celui du segment amont deja fixe), le
    PMS (>= pression max que verra la conduite) et les materiaux autorises (criteres de choix), on
    retient la ligne la moins chere.
  - Gravitaire, augmentation iterative du DN (consigne utilisateur) : quand la pression minimale
    n'est pas tenue a un noeud, le DN du segment AMONT de ce noeud est augmente au palier
    catalogue superieur, en balayant les noeuds en defaut de l'amont vers l'aval (cf.
    solve_gravitaire_troncon), puis toute la passe est recalculee — plusieurs passes successives
    si besoin (plafonnees, garde-fou anti-boucle infinie). Cette augmentation ne va jamais au-dela
    du DN qui ferait tomber la vitesse sous la vitesse min (meme plafond que ci-dessus) : au-dela,
    l'alerte "pression insuffisante" persiste plutot que de continuer a grossir indefiniment.
  - Darcy-Weisbach + Colebrook-White (resolution iterative, pas d'approximation) pour la perte de
    charge lineaire unitaire ; regime laminaire (Re<2300) via f=64/Re. Majoration (%) appliquee a
    la perte lineaire pour approcher les pertes de charge singulieres (Preferences).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

GRAVITY_M_S2 = 9.81

# Un critere de choix des materiaux (Preferences) peut dependre du DN de la ligne candidate elle-
# meme (ex. "PEHD seul en dessous de DN110") — d'ou un callable plutot qu'un simple ensemble fige :
# retourne None (aucune restriction) ou l'ensemble des materiaux autorises pour ce DN.
AllowedMaterialsFn = Callable[[int], Optional[frozenset[str]]]


def kinematic_viscosity_m2s(temperature_c: float) -> float:
    """Viscosite cinematique de l'eau (m2/s) en fonction de la temperature (degC) — correlation
    empirique usuelle, valable ~0-100degC. Un point de depart editable (Preferences), pas une
    verite figee pour d'autres fluides que l'eau."""
    return 1.792e-6 / (1.0 + 0.0337 * temperature_c + 0.000221 * temperature_c**2)


def colebrook_white(reynolds: float, relative_roughness: float) -> float:
    """Facteur de frottement de Darcy f. Regime laminaire (Re<2300) : f=64/Re. Turbulent :
    resolution iterative de Colebrook-White (amorcee par l'approximation explicite de Swamee-Jain,
    puis affinee par substitution successive — converge en quelques iterations)."""
    if reynolds <= 0:
        return 0.0
    if reynolds < 2300:
        return 64.0 / reynolds
    f = 0.25 / (math.log10(relative_roughness / 3.7 + 5.74 / reynolds**0.9)) ** 2
    for _ in range(8):
        sqrt_f = math.sqrt(f)
        rhs = -2.0 * math.log10(relative_roughness / 3.7 + 2.51 / (reynolds * sqrt_f))
        f_new = 1.0 / rhs**2
        if abs(f_new - f) < 1e-9:
            f = f_new
            break
        f = f_new
    return f


def segment_hydraulics(
    flow_m3s: float, di_mm: float, roughness_mm: float, viscosity_m2s: float
) -> tuple[float, float]:
    """Retourne (vitesse m/s, perte de charge lineaire unitaire J en m/m) — Darcy-Weisbach avec f
    de Colebrook-White (ou laminaire)."""
    if di_mm <= 0:
        raise ValueError("DI doit etre positif")
    di_m = di_mm / 1000.0
    area_m2 = math.pi * di_m**2 / 4.0
    velocity = abs(flow_m3s) / area_m2
    if velocity <= 0:
        return 0.0, 0.0
    reynolds = velocity * di_m / viscosity_m2s
    relative_roughness = (roughness_mm / 1000.0) / di_m
    f = colebrook_white(reynolds, relative_roughness)
    j = f * (velocity**2) / (2 * GRAVITY_M_S2 * di_m)
    return velocity, j


def min_di_mm_for_velocity(flow_m3s: float, max_velocity_ms: Optional[float]) -> float:
    if not max_velocity_ms or max_velocity_ms <= 0 or flow_m3s <= 0:
        return 0.0
    area_m2 = abs(flow_m3s) / max_velocity_ms
    return math.sqrt(4 * area_m2 / math.pi) * 1000.0


def max_di_mm_for_velocity(flow_m3s: float, min_velocity_ms: Optional[float]) -> float:
    """DI au-dela duquel la vitesse tomberait sous `min_velocity_ms` — plafond symetrique de
    `min_di_mm_for_velocity` (Preferences, consigne utilisateur : vitesse min par defaut 0.2 m/s).
    Sert a empecher la tentative iterative d'augmentation du DN gravitaire (cf.
    solve_gravitaire_troncon) de grossir un segment au point de rendre l'ecoulement trop lent —
    pas de plafond (`inf`) si aucune vitesse min n'est configuree."""
    if not min_velocity_ms or min_velocity_ms <= 0 or flow_m3s <= 0:
        return math.inf
    area_m2 = abs(flow_m3s) / min_velocity_ms
    return math.sqrt(4 * area_m2 / math.pi) * 1000.0


@dataclass(frozen=True)
class CatalogPipe:
    id: int
    dn: int
    di_mm: float
    material: str
    pressure_class: str
    pms_m: float
    price: float
    roughness_mm: float
    active: bool = True


@dataclass(frozen=True)
class SegmentSpec:
    id: str
    length_m: float
    flow_m3s: float
    max_velocity_ms: Optional[float] = None
    # Preferences, consigne utilisateur (defaut 0.2 m/s) : plafonne le DN choisi pour ne jamais
    # tomber sous cette vitesse — sizing initial (les deux regimes) ET tentative iterative
    # d'augmentation du DN gravitaire (cf. max_di_mm_for_velocity), qui s'arrete des qu'elle
    # l'atteindrait plutot que de grossir indefiniment.
    min_velocity_ms: Optional[float] = None
    # Contrainte Materiau/DN forcee (fenetre "Modifier le tronçon", ou contrainte d'homogeneisation
    # des classes — consigne utilisateur) : ce segment n'est plus auto-dimensionne (aucune recherche
    # catalogue par vitesse/PMS, cf. _resolve_forced_pipe). Si `forced_pressure_class` (ci-dessous)
    # n'est PAS renseigne (cas historique, "Modifier le tronçon" seul), la classe de pression la
    # moins chere disponible pour ce (materiau, DN) est retenue automatiquement. S'il L'EST (ex.
    # homogeneisation, qui force les trois a la fois pour figer le DN SANS perdre la classe choisie
    # par l'utilisateur), c'est EXACTEMENT cette classe qui est retenue — jamais une autre, meme
    # moins chere. Dans les deux cas, le calcul s'applique meme si la pression/vitesse resultante
    # viole une contrainte (alerte informative, jamais bloquante, contrairement au dimensionnement
    # automatique). Toujours ensemble : aucun sens a l'un sans l'autre.
    forced_material: Optional[str] = None
    forced_dn: Optional[int] = None
    # Contrainte PARTIELLE par plage de PK (consigne utilisateur, glossaire Piquet/Segment/Troncon —
    # ex. "FD partout, DN500 seulement entre pk 1550 et 5664") : contrairement a forced_material/
    # forced_dn ci-dessus (les DEUX ensemble, cf. docstring) qui figent aussi ce champ s'il est
    # renseigne, seuls les champs effectivement renseignes ici sont fixes quand material/dn ne sont
    # PAS tous les deux donnes — les autres restent choisis automatiquement (le moins cher
    # respectant vitesse/PMS/materiaux autorises parmi ce qui reste). Peut coexister avec un seul
    # des deux champs ci-dessus (ex. forced_dn seul, sans forced_material) — resolu par
    # routers/network.py a partir de Segment.constraints avant construction du SegmentSpec.
    forced_pressure_class: Optional[str] = None


@dataclass(frozen=True)
class SegmentCalcResult:
    id: str
    material: str
    pressure_class: str
    dn: int
    di_mm: float
    roughness_mm: float
    flow_m3s: float
    velocity_ms: float
    head_loss_unit: float
    head_loss_segment: float
    head_loss_cumulative: float


@dataclass(frozen=True)
class NodeCalcResult:
    node_id: str
    piezo_head: float
    pressure_dynamic: Optional[float] = None
    pressure_static_max: Optional[float] = None
    pressure_static_min: Optional[float] = None


@dataclass(frozen=True)
class TronconCalcResult:
    segments: list[SegmentCalcResult] = field(default_factory=list)
    nodes: list[NodeCalcResult] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)


def _candidates(
    catalog: list[CatalogPipe],
    min_di_mm: float,
    dn_min: Optional[int],
    dn_max: Optional[int],
    allowed_materials_fn: Optional[AllowedMaterialsFn],
    min_pms_m: float = 0.0,
    max_di_mm: float = math.inf,
    exact_pressure_class: Optional[str] = None,
) -> list[CatalogPipe]:
    def material_ok(p: CatalogPipe) -> bool:
        if allowed_materials_fn is None:
            return True
        allowed = allowed_materials_fn(p.dn)
        return allowed is None or p.material in allowed

    return sorted(
        (
            p
            for p in catalog
            if p.active
            and p.di_mm >= min_di_mm - 1e-9
            and p.di_mm <= max_di_mm + 1e-9
            and p.pms_m >= min_pms_m - 1e-9
            and (dn_min is None or p.dn >= dn_min)
            and (dn_max is None or p.dn <= dn_max)
            and (exact_pressure_class is None or p.pressure_class == exact_pressure_class)
            and material_ok(p)
        ),
        key=lambda p: (p.price, p.dn, p.di_mm),
    )


def _partial_forced_material_fn(
    forced_material: Optional[str], allowed_materials_fn: Optional[AllowedMaterialsFn]
) -> Optional[AllowedMaterialsFn]:
    """Restreint au materiau force (contrainte partielle par plage de PK, consigne utilisateur) s'il
    y en a un ; sinon retombe sur la fonction "materiaux autorises" habituelle (Preferences)."""
    if forced_material is None:
        return allowed_materials_fn
    return lambda dn: frozenset({forced_material})


def _resolve_forced_pipe(
    catalog: list[CatalogPipe], material: str, dn: int, min_pms_m: float, pressure_class: Optional[str] = None
) -> tuple[Optional[CatalogPipe], bool]:
    """Pour un (materiau, DN) force (consigne utilisateur) : si `pressure_class` est EGALEMENT
    fourni (ex. contrainte d'homogeneisation, qui force desormais les trois champs a la fois pour
    figer le DN sans perdre la classe choisie par l'utilisateur — sinon elle serait silencieusement
    ignoree et recalculee a la moins chere, ce qui viderait l'homogeneisation de son sens), retient
    EXACTEMENT cette ligne catalogue (le DI peut alors varier avec la classe pour les materiaux ou
    elle en depend, jamais le DN) ; sinon (ex. "Modifier le tronçon" sans classe forcee, seul cas
    historique), retient la ligne active la moins chere satisfaisant `min_pms_m`, ou a defaut
    (aucune ne le respecte) la moins chere tout court. Jamais un echec silencieux, le 2e element du
    tuple (`pms_ok`) indique si le PMS requis est effectivement tenu, a charge de l'appelant
    d'alerter si non. `None` si la combinaison n'existe meme pas dans le catalogue actif (ne devrait
    pas arriver pour materiau+DN seuls, ecarte a la saisie cote API — cf.
    services/catalog.py:material_dn_exists ; possible pour une classe precise si desactivee depuis)."""
    matches = [p for p in catalog if p.active and p.material == material and p.dn == dn]
    if not matches:
        return None, False
    if pressure_class is not None:
        exact = [p for p in matches if p.pressure_class == pressure_class]
        if not exact:
            return None, False
        chosen = exact[0]
        return chosen, chosen.pms_m >= min_pms_m - 1e-9
    meeting_pms = [p for p in matches if p.pms_m >= min_pms_m - 1e-9]
    pool = meeting_pms or matches
    chosen = min(pool, key=lambda p: (p.price, p.pressure_class))
    return chosen, bool(meeting_pms)


def _node_label(node_id: str, node_pk: Optional[dict[str, float]]) -> str:
    """Repere lisible pour les messages d'alerte — le PK du piquet si connu (fourni par
    l'appelant, cf. routers/network.py), sinon l'id brut en repli (tests unitaires notamment)."""
    if node_pk is not None and node_id in node_pk:
        return f"PK {node_pk[node_id]:.0f} m"
    return f"nœud {node_id}"


# Prefixe repere des alertes "zone d'exclusion" (Preferences, consigne utilisateur : pourcentage
# de la longueur du tronçon depuis son ouvrage de depart ou la contrainte de pression min n'est
# pas opposable) — jamais bloquantes, cf. routers/network.py:run_calculation qui les distingue des
# alertes normales par ce prefixe pour ne jamais reinitialiser un tronçon a cause d'elles seules.
EXCLUSION_ZONE_ALERT_MARKER = "Zone d'exclusion (pression min)"

# Prefixe repere (consigne utilisateur : "ne bloque plus le calcul pour une question de pression
# minimale, affiche juste une alerte") — signale a l'appelant (routers/network.py) qu'un manque de
# pression (residuelle/min, ou niveau de reservoir insuffisant pour les tenir) ne doit PLUS
# reinitialiser le tronçon : le dimensionnement calcule (DN/materiau/vitesse) reste applique tel
# quel, seule l'alerte informe que la pression exigee n'est pas entierement tenue. Distinct de
# l'alerte hydrostatique (_check_hydrostatic_feasibility, terrain au-dessus de la cote du
# reservoir) qui, elle, ne produit aucun resultat exploitable (segments vides) et reste donc geree
# a part par la proposition de repositionnement.
MIN_PRESSURE_ALERT_MARKER = "Pression minimale non garantie"

# Tolerance (m) sur les comparaisons de PK contre la borne de la zone d'exclusion — bien plus
# large que la precision flottante habituelle (1e-9) car le PK du dernier point de terrain
# echantillonne et celui du noeud de fin peuvent differer de quelques millimetres selon leur mode
# de calcul respectif (import KML vs interpolation) ; sans cette marge, un pourcentage couvrant
# tout le tronçon (100%) pourrait laisser echapper le tout dernier point par un pur artefact
# d'arrondi, contredisant l'intention de l'utilisateur.
_EXCLUSION_ZONE_PK_EPSILON_M = 1e-3


def _exclusion_zone_end_pk(
    node_pk: Optional[dict[str, float]], start_node: str, end_node: str, exclusion_m: Optional[float]
) -> Optional[float]:
    """PK au-dela duquel la contrainte de pression min redevient opposable — longueur, en METRES,
    propre au tronçon (consigne utilisateur : `Segment.min_pressure_exclusion_m`, plus un
    pourcentage global de Preferences), depuis son ouvrage de depart. `None` (zone desactivee) si
    la longueur ou les PK sont indisponibles."""
    if not exclusion_m or exclusion_m <= 0 or not node_pk:
        return None
    start_pk = node_pk.get(start_node)
    end_pk = node_pk.get(end_node)
    if start_pk is None or end_pk is None:
        return None
    return min(start_pk + exclusion_m, end_pk)


def _required_pressure_by_node(
    node_ids_ordered: list[str],
    min_pressure: Optional[float],
    downstream_residual_pressure: Optional[float],
    node_pk: Optional[dict[str, float]] = None,
    exclusion_end_pk: Optional[float] = None,
) -> tuple[dict[str, float], list[str]]:
    """`min_pressure` (si fourni) s'applique a tous les noeuds du troncon SAUF le tout premier —
    ce noeud est l'ouvrage source (reservoir ou station de pompage) lui-meme, pas un point de la
    conduite : sa "pression" ne depend que du niveau de l'ouvrage et de l'altitude du terrain a cet
    endroit, jamais du dimensionnement du troncon (revoir le decoupage du trace n'y changerait
    rien) — l'y appliquer produirait de fausses alertes. Le dernier noeud (le plus aval) doit EN
    PLUS respecter `downstream_residual_pressure` — on retient le plus exigeant des deux la ou ils
    se superposent (la residuelle aval s'applique TOUJOURS a ce noeud, meme dans la zone
    d'exclusion — seule `min_pressure` en est desactivable, consigne utilisateur). Renvoie aussi
    la liste des noeuds EXCLUS (dans la zone, Preferences) qui auraient ete soumis a `min_pressure`
    sans elle — a l'appelant de les verifier separement une fois les pressions connues, pour une
    alerte informative non bloquante (cf. _check_excluded_nodes_pressure)."""
    required: dict[str, float] = {}
    excluded: list[str] = []
    if min_pressure is not None:
        for nid in node_ids_ordered[1:]:
            pk = node_pk.get(nid) if node_pk else None
            if exclusion_end_pk is not None and pk is not None and pk <= exclusion_end_pk + _EXCLUSION_ZONE_PK_EPSILON_M:
                excluded.append(nid)
                continue
            required[nid] = min_pressure
    end_node = node_ids_ordered[-1]
    end_required = None if end_node in excluded else min_pressure
    if downstream_residual_pressure is not None:
        end_required = max(end_required, downstream_residual_pressure) if end_required is not None else downstream_residual_pressure
    if end_required is not None:
        required[end_node] = end_required
    return required, excluded


def _check_excluded_nodes_pressure(
    node_ids_ordered: list[str],
    node_pk: Optional[dict[str, float]],
    nodes: dict[str, "NodeCalcResult"],
    min_pressure: Optional[float],
    excluded_node_ids: list[str],
) -> list[str]:
    """Verifie a titre INFORMATIF (jamais bloquant) la pression min aux noeuds de la zone
    d'exclusion (Preferences, consigne utilisateur) — le calcul s'applique quoi qu'il arrive, une
    alerte au prefixe reconnu (EXCLUSION_ZONE_ALERT_MARKER) signale simplement le depassement."""
    if min_pressure is None or not excluded_node_ids:
        return []
    violations = [
        (nid, nodes[nid].pressure_dynamic or 0.0)
        for nid in excluded_node_ids
        if (nodes[nid].pressure_dynamic or 0.0) < min_pressure - 1e-6
    ]
    if not violations:
        return []
    labels = ", ".join(_node_label(nid, node_pk) for nid, _ in violations)
    worst = min(v[1] for v in violations)
    return [
        f"{EXCLUSION_ZONE_ALERT_MARKER} : pression sous le minimum requis ({min_pressure:.1f} m, pire "
        f"cas {worst:.1f} m) à {labels} — dans la zone d'exclusion (Préférences), alerte informative, "
        f"calcul non bloqué."
    ]


def _check_terrain_pressure(
    node_ids_ordered: list[str],
    node_pk: Optional[dict[str, float]],
    node_cotes: dict[str, float],
    min_pressure: Optional[float],
    terrain_samples: Optional[list[tuple[float, float]]],
    exclusion_end_pk: Optional[float] = None,
) -> list[str]:
    """Verifie la pression sur CHAQUE point echantillonne du profil de terrain (pas seulement aux
    noeuds reels, cf. docstring du module) une fois la ligne piezometrique finale connue. Une seule
    alerte agregee (jamais une par point — un terrain accidente en produirait des centaines) : PK de
    debut/fin de la zone en defaut et pire cas rencontre. Les points dans la zone d'exclusion
    (Preferences, consigne utilisateur) sont rapportes a part, dans une alerte informative jamais
    bloquante (cf. EXCLUSION_ZONE_ALERT_MARKER)."""
    if min_pressure is None or not terrain_samples or not node_pk:
        return []
    violations: list[tuple[float, float, float]] = []
    excluded_violations: list[tuple[float, float, float]] = []
    for i in range(len(node_ids_ordered) - 1):
        a, b = node_ids_ordered[i], node_ids_ordered[i + 1]
        pk_a, pk_b = node_pk.get(a), node_pk.get(b)
        if pk_a is None or pk_b is None:
            continue
        cote_a, cote_b = node_cotes[a], node_cotes[b]
        span = pk_b - pk_a
        for pk, z in terrain_samples:
            if pk < pk_a - 1e-6 or pk > pk_b + 1e-6:
                continue
            t = 0.0 if span <= 1e-9 else (pk - pk_a) / span
            cote = cote_a + t * (cote_b - cote_a)
            pressure = cote - z
            if pressure < min_pressure - 1e-6:
                target = excluded_violations if exclusion_end_pk is not None and pk <= exclusion_end_pk + _EXCLUSION_ZONE_PK_EPSILON_M else violations
                target.append((pk, z, pressure))
    alerts: list[str] = []
    if violations:
        worst = min(violations, key=lambda v: v[2])
        pk_min = min(v[0] for v in violations)
        pk_max = max(v[0] for v in violations)
        alerts.append(
            f"{MIN_PRESSURE_ALERT_MARKER} : pression minimale non respectée sur le terrain entre "
            f"PK {pk_min:.0f} m et PK {pk_max:.0f} m ({len(violations)} point(s) échantillonné(s), "
            f"pire cas {worst[2]:.1f} m obtenus au PK {worst[0]:.0f} m pour {min_pressure:.1f} m "
            f"requis) — revoir le découpage du tracé (brise-charge, tronçon plus court...)."
        )
    if excluded_violations:
        worst = min(excluded_violations, key=lambda v: v[2])
        pk_min = min(v[0] for v in excluded_violations)
        pk_max = max(v[0] for v in excluded_violations)
        alerts.append(
            f"{EXCLUSION_ZONE_ALERT_MARKER} : terrain sous la pression minimale entre PK {pk_min:.0f} m et "
            f"PK {pk_max:.0f} m ({len(excluded_violations)} point(s), pire cas {worst[2]:.1f} m pour "
            f"{min_pressure:.1f} m requis) — dans la zone d'exclusion (Préférences), alerte informative, "
            f"calcul non bloqué."
        )
    return alerts


def _check_hydrostatic_feasibility(
    upstream_level_min: Optional[float],
    node_pk: Optional[dict[str, float]],
    start_node: str,
    terrain_samples: Optional[list[tuple[float, float]]],
) -> list[str]:
    """Pre-check AVANT toute reconstruction (consigne utilisateur) : le niveau du reservoir amont
    (`upstream_level_min`, LA cote de reference garantie deja utilisee partout ailleurs dans ce
    module) est une donnee physique fixe — la ligne piezometrique ne peut jamais depasser le
    niveau du reservoir, donc si le terrain atteint ou depasse cette cote quelque part, aucun
    dimensionnement de conduite ne peut jamais y faire passer un ecoulement gravitaire (inutile de
    lancer la reconstruction, qui produirait des pressions non-sens). Ne s'applique que si un
    niveau a effectivement ete renseigne (`None` = pas encore configure, pas de faux positif)."""
    if upstream_level_min is None or not terrain_samples:
        return []
    violations = [(pk, z) for pk, z in terrain_samples if z >= upstream_level_min - 1e-6]
    if not violations:
        return []
    worst = max(violations, key=lambda v: v[1])
    pk_min = min(v[0] for v in violations)
    pk_max = max(v[0] for v in violations)
    return [
        f"Le terrain atteint ou dépasse la cote hydrostatique du réservoir amont "
        f"({_node_label(start_node, node_pk)}, niveau min = {upstream_level_min:.1f} m) entre PK "
        f"{pk_min:.0f} m et PK {pk_max:.0f} m ({len(violations)} point(s), pire cas Z={worst[1]:.1f} m "
        f"au PK {worst[0]:.0f} m) — l'écoulement gravitaire y est physiquement impossible quel que "
        f"soit le dimensionnement retenu, revoir le découpage du tracé (brise-charge, tronçon plus "
        f"court...)."
    ]


def _gravitaire_pass(
    node_ids_ordered: list[str],
    node_ground_z: dict[str, float],
    segments_ordered: list[SegmentSpec],
    upstream_level_max: float,
    effective_upstream_level_min: float,
    required_by_node: dict[str, float],
    catalog: list[CatalogPipe],
    singular_loss_markup_pct: float,
    viscosity: float,
    allowed_materials_fn: Optional[AllowedMaterialsFn],
    node_pk: Optional[dict[str, float]],
    min_dn_by_segment: dict[str, int],
    forced_dn_by_segment: Optional[dict[str, int]] = None,
) -> tuple[dict[str, NodeCalcResult], list[SegmentCalcResult], list[str]]:
    """Une passe complete de la reconstruction AVAL -> AMONT + translation (cf. docstring module),
    parametree par un plancher de DN additionnel par segment (`min_dn_by_segment`) — permet a
    `solve_gravitaire_troncon` de ré-essayer avec un DN plus gros sur un segment precis quand la
    pression minimale n'est pas tenue (consigne utilisateur), sans dupliquer cette logique — et par
    un DN EXACT impose par segment (`forced_dn_by_segment`, distinct de `Segment.forced_dn` saisi
    par l'utilisateur) utilise par l'optimisation telescopique de `solve_gravitaire_troncon` : la
    classe de pression/le materiau restent choisis automatiquement (le moins cher respectant le PMS
    et les materiaux autorises), seul le DN est impose tel quel pour ce segment."""
    alerts: list[str] = []
    nodes: dict[str, NodeCalcResult] = {}
    for nid in node_ids_ordered:
        z = node_ground_z[nid]
        nodes[nid] = NodeCalcResult(
            node_id=nid, piezo_head=effective_upstream_level_min,
            pressure_static_max=upstream_level_max - z, pressure_static_min=effective_upstream_level_min - z,
        )

    end_node = node_ids_ordered[-1]
    end_required = required_by_node.get(end_node, 0.0)
    nodes[end_node] = replace(
        nodes[end_node], piezo_head=node_ground_z[end_node] + end_required, pressure_dynamic=end_required
    )

    dn_floor: Optional[int] = None
    results_reversed: list[SegmentCalcResult] = []
    for i in range(len(segments_ordered) - 1, -1, -1):
        seg = segments_ordered[i]
        upstream_node = node_ids_ordered[i]
        downstream_node = node_ids_ordered[i + 1]
        min_di = min_di_mm_for_velocity(seg.flow_m3s, seg.max_velocity_ms)
        max_di = max_di_mm_for_velocity(seg.flow_m3s, seg.min_velocity_ms)
        max_pms_needed = max(
            nodes[upstream_node].pressure_static_max or 0.0,
            nodes[downstream_node].pressure_static_max or 0.0,
        )
        seg_label = f"Segment entre {_node_label(upstream_node, node_pk)} et {_node_label(downstream_node, node_pk)}"
        if seg.forced_material is not None and seg.forced_dn is not None:
            # Materiau/DN forces (consigne utilisateur) : plus d'auto-dimensionnement pour ce
            # segment. Si une classe est EN PLUS forcee (homogeneisation), elle est retenue
            # exactement telle quelle (cf. _resolve_forced_pipe) ; sinon la moins chere disponible
            # est retenue automatiquement. Le calcul s'applique meme si le PMS/la vitesse n'est pas
            # respecte (alerte informative, jamais bloquante contrairement au dimensionnement
            # automatique).
            cand, pms_ok = _resolve_forced_pipe(
                catalog, seg.forced_material, seg.forced_dn, max_pms_needed, seg.forced_pressure_class
            )
            if cand is None:
                class_suffix = f" {seg.forced_pressure_class}" if seg.forced_pressure_class else ""
                alerts.append(
                    f"{seg_label} : aucune conduite active {seg.forced_material} DN{seg.forced_dn}"
                    f"{class_suffix} au catalogue — vérifier la fenêtre Conduites."
                )
                candidates = _candidates(catalog, 0.0, None, None, None) or list(catalog)
                cand = candidates[0]
            elif not pms_ok:
                alerts.append(
                    f"{seg_label} : le DN {seg.forced_dn} force en {seg.forced_material} ne respecte pas "
                    f"le PMS requis ({max_pms_needed:.1f} m, classe {cand.pressure_class} = {cand.pms_m:.1f} m) "
                    f"— calcul effectué malgré la contrainte matériau/DN forcée."
                )
        elif seg.forced_material is not None or seg.forced_dn is not None or seg.forced_pressure_class is not None:
            # Contrainte PARTIELLE (materiau et/ou DN et/ou classe — consigne utilisateur,
            # contraintes par plage de PK) : seuls les champs renseignes sont fixes, le reste est
            # choisi automatiquement (le moins cher respectant vitesse/PMS/materiaux autorises
            # parmi ce qui reste) — une seule resolution, pas d'ajustement iteratif. Si le DN
            # LUI-MEME n'est pas force (ex. materiau seul, comme une contrainte Matériau posee
            # depuis la bande de caracteristiques), il reste soumis au plancher de telescopage
            # `dn_floor` — consigne utilisateur : "le choix des DN ne respecte pas le
            # téléscopage" ; un materiau force seul ne doit pas devenir un etranglement local
            # (DN qui retrecit puis se rouvre juste apres) alors que l'utilisateur n'a jamais
            # demande a changer le DN, seulement le materiau. Seul un DN EXPLICITEMENT force par
            # l'utilisateur reste exempt du plancher (son choix delibere prime).
            material_fn = _partial_forced_material_fn(seg.forced_material, allowed_materials_fn)
            dn_min = seg.forced_dn if seg.forced_dn is not None else dn_floor
            candidates = _candidates(
                catalog, min_di, dn_min, seg.forced_dn, material_fn, max_pms_needed, max_di,
                exact_pressure_class=seg.forced_pressure_class,
            )
            if not candidates and dn_min is not None and seg.forced_dn is None:
                # Le plancher de telescopage n'est pas atteignable avec ce materiau/cette classe
                # (ex. un materiau dont le plus gros DN au catalogue est sous le plancher etabli en
                # aval) — on relache le plancher plutot que d'aller directement au repli suivant
                # (qui, lui, ignore aussi vitesse/PMS) : mieux vaut un etranglement local que de
                # sacrifier vitesse/PMS pour rien, alors que le seul probleme est le plancher.
                candidates = _candidates(
                    catalog, min_di, None, seg.forced_dn, material_fn, max_pms_needed, max_di,
                    exact_pressure_class=seg.forced_pressure_class,
                )
                if candidates:
                    alerts.append(
                        f"{seg_label} : le plancher de télescopage (DN {dn_min}) n'est pas atteignable "
                        f"avec la contrainte matériau/classe imposée — DN choisi librement pour cette "
                        f"contrainte, télescopage non respecté ici."
                    )
            if not candidates:
                candidates = _candidates(
                    catalog, 0.0, None, seg.forced_dn, material_fn, 0.0, math.inf,
                    exact_pressure_class=seg.forced_pressure_class,
                )
                if candidates:
                    alerts.append(
                        f"{seg_label} : la contrainte partielle imposée ne permet de respecter ni la "
                        f"vitesse ni le PMS requis — conduite retenue malgré tout, alerte informative."
                    )
                else:
                    alerts.append(
                        f"{seg_label} : aucune conduite active ne correspond à la contrainte partielle "
                        f"imposée — vérifier la fenêtre Conduites."
                    )
                    candidates = _candidates(catalog, 0.0, None, None, None) or list(catalog)
            cand = candidates[0]
        elif forced_dn_by_segment is not None and seg.id in forced_dn_by_segment:
            # DN exact impose pour l'optimisation telescopique (consigne utilisateur) — materiau/
            # classe restent choisis automatiquement (le moins cher respectant PMS/materiaux
            # autorises) a CE DN precis, sans plancher ni plafond : c'est a l'appelant
            # (solve_gravitaire_troncon) de ne proposer que des DN respectant deja la contrainte de
            # non-croissance vers l'aval.
            exact_dn = forced_dn_by_segment[seg.id]
            candidates = _candidates(catalog, min_di, exact_dn, exact_dn, allowed_materials_fn, max_pms_needed, max_di)
            if not candidates:
                alerts.append(
                    f"{seg_label} : aucune conduite active DN{exact_dn} ne respecte vitesse/PMS/"
                    f"matériaux autorisés — optimisation de diamètre non appliquée ici."
                )
                candidates = _candidates(catalog, 0.0, exact_dn, exact_dn, None) or list(catalog)
            cand = candidates[0]
        else:
            effective_dn_floor = dn_floor
            forced_min_dn = min_dn_by_segment.get(seg.id)
            if forced_min_dn is not None:
                effective_dn_floor = forced_min_dn if effective_dn_floor is None else max(effective_dn_floor, forced_min_dn)

            candidates = _candidates(catalog, min_di, effective_dn_floor, None, allowed_materials_fn, max_pms_needed, max_di)
            if not candidates:
                alerts.append(
                    f"{seg_label} : aucune conduite active ne respecte vitesse/PMS/matériaux autorisés "
                    f"(DN plancher {effective_dn_floor}) — vérifier le catalogue Conduites."
                )
                candidates = _candidates(catalog, 0.0, effective_dn_floor, None, None) or list(catalog)
            cand = candidates[0]
        velocity, j = segment_hydraulics(seg.flow_m3s, cand.di_mm, cand.roughness_mm, viscosity)
        if seg.forced_dn is not None:
            if seg.max_velocity_ms and velocity > seg.max_velocity_ms + 1e-6:
                alerts.append(
                    f"{seg_label} : vitesse {velocity:.2f} m/s supérieure à la vitesse max "
                    f"({seg.max_velocity_ms:.2f} m/s) pour le DN {seg.forced_dn} forcé — calcul "
                    f"effectué malgré la contrainte matériau/DN forcée."
                )
            if seg.min_velocity_ms and velocity < seg.min_velocity_ms - 1e-6:
                alerts.append(
                    f"{seg_label} : vitesse {velocity:.2f} m/s inférieure à la vitesse min "
                    f"({seg.min_velocity_ms:.2f} m/s) pour le DN {seg.forced_dn} forcé — calcul "
                    f"effectué malgré la contrainte matériau/DN forcée."
                )
        loss = j * seg.length_m * (1 + singular_loss_markup_pct / 100)
        cote_upstream = nodes[downstream_node].piezo_head + loss
        pressure_upstream = cote_upstream - node_ground_z[upstream_node]

        results_reversed.append(
            SegmentCalcResult(
                id=seg.id, material=cand.material, pressure_class=cand.pressure_class, dn=cand.dn,
                di_mm=cand.di_mm, roughness_mm=cand.roughness_mm, flow_m3s=seg.flow_m3s,
                velocity_ms=velocity, head_loss_unit=j, head_loss_segment=loss, head_loss_cumulative=0.0,
            )
        )
        nodes[upstream_node] = replace(nodes[upstream_node], piezo_head=cote_upstream, pressure_dynamic=pressure_upstream)
        # Ne JAMAIS laisser le plancher DIMINUER (consigne utilisateur : "le choix des DN ne
        # respecte pas le téléscopage") — une contrainte forcee/partielle (branches ci-dessus,
        # explicitement exemptees du plancher pour respecter le choix de l'utilisateur) peut
        # retenir un DN plus PETIT que ce que l'auto-dimensionnement aval avait deja etabli comme
        # plancher ; le laisser ecraser `dn_floor` faisait "retrecir" le plancher pour le segment
        # encore plus amont (libre, lui, non exempte), creant un etranglement local qui se rouvre
        # juste apres (DN grand -> DN petit force -> DN grand a nouveau), au lieu du telescopage
        # attendu. Pour la branche libre (else ci-dessus), `cand.dn` est deja >= `dn_floor` par
        # construction (passe en `dn_min` a `_candidates`) : ce max est donc un no-op pour elle,
        # et ne resserre le plancher QUE si la contrainte forcee a elle-meme choisi plus grand.
        dn_floor = cand.dn if dn_floor is None else max(dn_floor, cand.dn)

    # Cote "necessaire" reconstruite en tete vs. cote REELLEMENT disponible (le reservoir ne se
    # "dimensionne" pas comme une pompe) — translation de tout le profil si marge positive, alerte
    # sinon (cf. docstring module).
    start_node = node_ids_ordered[0]
    offset = effective_upstream_level_min - nodes[start_node].piezo_head
    if offset < -1e-6:
        alerts.append(
            f"{MIN_PRESSURE_ALERT_MARKER} : niveau du réservoir amont "
            f"({_node_label(start_node, node_pk)}, min = {effective_upstream_level_min:.1f} m) "
            f"insuffisant de {-offset:.1f} m pour garantir la pression minimale sur l'ensemble du "
            f"tronçon — revoir le découpage du tracé (brise-charge, tronçon plus court...)."
        )

    for nid in node_ids_ordered:
        n = nodes[nid]
        nodes[nid] = replace(n, piezo_head=n.piezo_head + offset, pressure_dynamic=(n.pressure_dynamic or 0.0) + offset)

    for nid, required in required_by_node.items():
        actual = nodes[nid].pressure_dynamic or 0.0
        if actual < required - 1e-6:
            alerts.append(
                f"{MIN_PRESSURE_ALERT_MARKER} : pression insuffisante au {_node_label(nid, node_pk)} "
                f"({actual:.1f} m obtenus, {required:.1f} m requis) — revoir le découpage du tracé "
                f"(brise-charge, tronçon plus court...)."
            )

    results = list(reversed(results_reversed))
    running = 0.0
    for idx, r in enumerate(results):
        running += r.head_loss_segment
        results[idx] = replace(r, head_loss_cumulative=running)

    return nodes, results, alerts


# Garde-fou anti-boucle infinie pour la tentative iterative d'augmentation de DN ci-dessous
# (consigne utilisateur : "processus iteratif", imperfection acceptee au-dela de ce plafond).
_MAX_GRAVITAIRE_DN_BUMP_ITERATIONS = 20

# Garde-fou anti-boucle infinie pour la tentative iterative d'augmentation de la CLASSE DE
# PRESSION en refoulement (cf. solve_refoulement_troncon) — la pression dynamique depend des DN
# choisis, qui peuvent eux-memes changer legerement de DI en changeant de classe, d'ou la
# re-iteration complete jusqu'a stabilisation (converge generalement en 2-3 passes, ce plafond est
# une marge de securite).
_MAX_REFOULEMENT_PMS_ITERATIONS = 20


def solve_gravitaire_troncon(
    node_ids_ordered: list[str],
    node_ground_z: dict[str, float],
    segments_ordered: list[SegmentSpec],
    upstream_level_max: float,
    upstream_level_min: Optional[float],
    min_pressure: Optional[float],
    downstream_residual_pressure: Optional[float],
    catalog: list[CatalogPipe],
    singular_loss_markup_pct: float,
    fluid_temperature_c: float,
    allowed_materials_fn: Optional[AllowedMaterialsFn] = None,
    node_pk: Optional[dict[str, float]] = None,
    terrain_samples: Optional[list[tuple[float, float]]] = None,
    min_pressure_exclusion_m: Optional[float] = None,
) -> TronconCalcResult:
    """Gravitaire, sens AVAL -> AMONT (cf. docstring du module) : le niveau du reservoir est une
    donnee fixe, pas un choix de conception — on reconstruit depuis l'exigence de pression aval la
    cote necessaire en tete, on la compare au niveau reellement disponible, et on translate (ou on
    alerte si la marge est negative). `upstream_level_min` peut etre `None` (niveau pas encore
    renseigne dans "Modifier le tronçon") : le pre-check hydrostatique est alors simplement
    desactive, le reste du calcul utilise 0.0 comme avant (comportement inchange pour un appelant
    qui passait deja un float). Si la pression minimale n'est pas tenue a un noeud, une tentative
    iterative augmente le DN du segment AMONT de ce noeud (consigne utilisateur : "ce n'est pas
    grave, processus iteratif") avant de se resoudre a alerter."""
    effective_upstream_level_min = upstream_level_min if upstream_level_min is not None else 0.0

    hydrostatic_alerts = _check_hydrostatic_feasibility(
        upstream_level_min, node_pk, node_ids_ordered[0], terrain_samples
    )
    if hydrostatic_alerts:
        # Le calcul detaille n'a aucun sens physique si le terrain depasse deja la cote du
        # reservoir : aucun resultat construit, les noeuds sont explicitement remis a zero pour ne
        # pas laisser une ligne piezo perimee affichee (cf. network.py:run_calculation, qui
        # applique ces valeurs telles quelles).
        reset_nodes = [
            NodeCalcResult(
                node_id=nid, piezo_head=None, pressure_dynamic=None,
                pressure_static_max=None, pressure_static_min=None,
            )
            for nid in node_ids_ordered
        ]
        return TronconCalcResult(segments=[], nodes=reset_nodes, alerts=hydrostatic_alerts)

    viscosity = kinematic_viscosity_m2s(fluid_temperature_c)
    exclusion_end_pk = _exclusion_zone_end_pk(
        node_pk, node_ids_ordered[0], node_ids_ordered[-1], min_pressure_exclusion_m
    )
    required_by_node, excluded_node_ids = _required_pressure_by_node(
        node_ids_ordered, min_pressure, downstream_residual_pressure, node_pk, exclusion_end_pk
    )

    min_dn_by_segment: dict[str, int] = {}
    nodes: dict[str, NodeCalcResult] = {}
    results: list[SegmentCalcResult] = []
    pass_alerts: list[str] = []
    for attempt in range(_MAX_GRAVITAIRE_DN_BUMP_ITERATIONS + 1):
        nodes, results, pass_alerts = _gravitaire_pass(
            node_ids_ordered, node_ground_z, segments_ordered, upstream_level_max,
            effective_upstream_level_min, required_by_node, catalog, singular_loss_markup_pct,
            viscosity, allowed_materials_fn, node_pk, min_dn_by_segment,
        )
        violating_nodes = [
            nid for nid, required in required_by_node.items()
            if (nodes[nid].pressure_dynamic or 0.0) < required - 1e-6
        ]
        if not violating_nodes or attempt == _MAX_GRAVITAIRE_DN_BUMP_ITERATIONS:
            break

        # Le 1er noeud du troncon n'a pas de segment amont DANS ce troncon (c'est l'ouvrage source
        # lui-meme) — rien a augmenter pour lui, seule l'alerte reservoir peut le concerner.
        bumped_any = False
        dn_by_segment_id = {r.id: r.dn for r in results}
        for nid in violating_nodes:
            idx = node_ids_ordered.index(nid)
            if idx == 0:
                continue
            seg = segments_ordered[idx - 1]
            if seg.forced_material is not None or seg.forced_dn is not None or seg.forced_pressure_class is not None:
                # Contrainte (totale ou partielle, consigne utilisateur) : jamais touche par
                # l'augmentation iterative, meme si le noeud aval viole la pression — l'alerte de
                # pression persiste (le segment contraint garde sa resolution quoi qu'il arrive).
                continue
            current_dn = dn_by_segment_id.get(seg.id)
            if current_dn is None:
                continue
            # Plafond de vitesse min (Preferences, consigne utilisateur) : ne pas grossir ce
            # segment au point de repasser sous cette vitesse — l'augmentation s'arrete la pour ce
            # segment (l'alerte "pression insuffisante" persiste alors, cf. verification finale de
            # la passe) plutot que de continuer indefiniment.
            max_di = max_di_mm_for_velocity(seg.flow_m3s, seg.min_velocity_ms)
            bigger = _candidates(catalog, 0.0, current_dn + 1, None, allowed_materials_fn, max_di_mm=max_di)
            if not bigger:
                continue
            new_floor = bigger[0].dn
            if new_floor > min_dn_by_segment.get(seg.id, 0):
                min_dn_by_segment[seg.id] = new_floor
                bumped_any = True
        if not bumped_any:
            break

    # Optimisation telescopique du diametre (consigne utilisateur, procedure validee explicitement) :
    # une fois une solution SANS aucune alerte obtenue (le DN "de base", le moins cher respectant
    # vitesse/PMS partout), on tente de la reduire par paliers catalogue successifs, en partant du
    # segment le plus AVAL et en remontant vers l'amont : DN(PK0) >= DN(fin de tronçon) doit
    # toujours etre respecte, donc chaque segment ne peut etre reduit qu'a un palier >= celui deja
    # retenu pour son voisin aval. Pour un segment donne, on retente le palier immediatement
    # inferieur, on reverifie l'ENSEMBLE du tronçon (recalcul complet — reduire un segment change sa
    # perte de charge, qui peut faire manquer la pression n'importe ou en amont), et on accepte tant
    # qu'aucune alerte n'apparait ; sinon on s'arrete pour ce segment (il garde son dernier DN
    # valide) et on passe au suivant, plus en amont. Les segments a materiau/DN force (consigne
    # utilisateur) ne sont jamais touches.
    if not violating_nodes and not pass_alerts:
        dn_by_segment_id = {r.id: r.dn for r in results}
        forced_dn_by_segment: dict[str, int] = dict(dn_by_segment_id)
        all_dns = sorted({p.dn for p in catalog if p.active})
        downstream_floor = 0
        for i in range(len(segments_ordered) - 1, -1, -1):
            seg = segments_ordered[i]
            if seg.forced_material is not None or seg.forced_dn is not None or seg.forced_pressure_class is not None:
                downstream_floor = forced_dn_by_segment[seg.id]
                continue
            current_dn = forced_dn_by_segment[seg.id]
            smaller_steps = sorted((d for d in all_dns if downstream_floor <= d < current_dn), reverse=True)
            for trial_dn in smaller_steps:
                trial_forced = dict(forced_dn_by_segment)
                trial_forced[seg.id] = trial_dn
                trial_nodes, trial_results, trial_alerts = _gravitaire_pass(
                    node_ids_ordered, node_ground_z, segments_ordered, upstream_level_max,
                    effective_upstream_level_min, required_by_node, catalog, singular_loss_markup_pct,
                    viscosity, allowed_materials_fn, node_pk, min_dn_by_segment, trial_forced,
                )
                if trial_alerts:
                    break
                forced_dn_by_segment = trial_forced
                nodes, results, pass_alerts = trial_nodes, trial_results, trial_alerts
            downstream_floor = forced_dn_by_segment[seg.id]

    alerts = list(pass_alerts)
    alerts.extend(
        _check_terrain_pressure(
            node_ids_ordered, node_pk,
            {nid: nodes[nid].piezo_head for nid in node_ids_ordered},
            min_pressure, terrain_samples, exclusion_end_pk,
        )
    )
    alerts.extend(_check_excluded_nodes_pressure(node_ids_ordered, node_pk, nodes, min_pressure, excluded_node_ids))

    return TronconCalcResult(segments=results, nodes=[nodes[nid] for nid in node_ids_ordered], alerts=alerts)


def solve_refoulement_troncon(
    node_ids_ordered: list[str],
    node_ground_z: dict[str, float],
    segments_ordered: list[SegmentSpec],
    min_pressure: Optional[float],
    downstream_residual_pressure: Optional[float],
    catalog: list[CatalogPipe],
    singular_loss_markup_pct: float,
    fluid_temperature_c: float,
    allowed_materials_fn: Optional[AllowedMaterialsFn] = None,
    node_pk: Optional[dict[str, float]] = None,
    terrain_samples: Optional[list[tuple[float, float]]] = None,
    min_pressure_exclusion_m: Optional[float] = None,
) -> TronconCalcResult:
    """Refoulement, sens AMONT -> AVAL (cf. docstring du module) : les DN sont choisis sur la seule
    contrainte de vitesse (+ decroissance vers l'aval), puis la plus petite cote de depart (H0, au
    premier piquet) qui garantit la pression minimale/residuelle est obtenue sous forme close — EN
    TOUT point du terrain echantillonne (`terrain_samples`), pas seulement aux noeuds reels : un
    point haut intermediaire jamais materialise par un noeud est donc lui aussi couvert, H0 est
    simplement augmentee jusqu'a ce qu'il le soit (consigne utilisateur : "pas de message d'erreur,
    il faut augmenter la cote piezometrique du 1er piquet jusqu'a ce que ca se regle" — contrairement
    au gravitaire, la cote de depart n'est pas une donnee fixe, une pompe se dimensionne plus fort).
    Seule une alerte de depassement de PMS reste possible (la pression, elle, ne peut pas etre
    "silencieusement" acceptee au-dela de ce que la conduite supporte)."""
    viscosity = kinematic_viscosity_m2s(fluid_temperature_c)

    exclusion_end_pk = _exclusion_zone_end_pk(
        node_pk, node_ids_ordered[0], node_ids_ordered[-1], min_pressure_exclusion_m
    )
    required_by_node, excluded_node_ids = _required_pressure_by_node(
        node_ids_ordered, min_pressure, downstream_residual_pressure, node_pk, exclusion_end_pk
    )

    # Choix des DN/classes ET calcul de H0 sont re-tentes ensemble tant qu'un segment retient une
    # classe de pression insuffisante pour la pression DYNAMIQUE finalement obtenue (consigne
    # utilisateur : "tu ne peux pas prevoir PN10 lorsque la pression est 12 bar") — contrairement au
    # gravitaire (pression hydrostatique connue d'avance), la pression de service en refoulement ne
    # se connait qu'une fois H0 determine, d'ou l'iteration : `min_pms_by_segment` releve le
    # plancher PMS d'un segment des que sa classe actuelle ne le couvre plus, et tout est recalcule
    # (un changement de classe peut legerement changer le DI donc les pertes donc H0).
    min_pms_by_segment: dict[str, float] = {}
    alerts: list[str] = []
    prelim: list[tuple[SegmentSpec, CatalogPipe, float, float]] = []
    cumulative_by_node: dict[str, float] = {}
    nodes: dict[str, NodeCalcResult] = {}
    h0 = 0.0
    excluded_terrain_points: list[tuple[float, float]] = []

    for attempt in range(_MAX_REFOULEMENT_PMS_ITERATIONS + 1):
        alerts = []
        dn_ceiling = None
        prelim = []
        for i, seg in enumerate(segments_ordered):
            seg_label = (
                f"Segment entre {_node_label(node_ids_ordered[i], node_pk)} et "
                f"{_node_label(node_ids_ordered[i + 1], node_pk)}"
            )
            min_pms_needed = min_pms_by_segment.get(seg.id, 0.0)
            if seg.forced_material is not None and seg.forced_dn is not None:
                # Materiau/DN forces (consigne utilisateur) : si une classe est EN PLUS forcee
                # (homogeneisation), elle est retenue exactement telle quelle (cf.
                # _resolve_forced_pipe) ; sinon la moins chere COUVRANT le PMS requis est retenue
                # si elle existe (comme en gravitaire, cf. solve_gravitaire_troncon) — a defaut la
                # moins chere tout court, avec alerte.
                cand, pms_ok = _resolve_forced_pipe(
                    catalog, seg.forced_material, seg.forced_dn, min_pms_needed, seg.forced_pressure_class
                )
                if cand is None:
                    class_suffix = f" {seg.forced_pressure_class}" if seg.forced_pressure_class else ""
                    alerts.append(
                        f"{seg_label} : aucune conduite active {seg.forced_material} DN{seg.forced_dn}"
                        f"{class_suffix} au catalogue — vérifier la fenêtre Conduites."
                    )
                    candidates = _candidates(catalog, 0.0, None, None, None) or list(catalog)
                    cand = candidates[0]
                elif not pms_ok and attempt == _MAX_REFOULEMENT_PMS_ITERATIONS:
                    alerts.append(
                        f"{seg_label} : le DN {seg.forced_dn} force en {seg.forced_material} ne "
                        f"respecte pas le PMS requis ({min_pms_needed:.1f} m, classe "
                        f"{cand.pressure_class} = {cand.pms_m:.1f} m) — calcul effectué malgré la "
                        f"contrainte matériau/DN forcée."
                    )
            elif seg.forced_material is not None or seg.forced_dn is not None or seg.forced_pressure_class is not None:
                # Contrainte PARTIELLE (materiau et/ou DN et/ou classe — consigne utilisateur,
                # contraintes par plage de PK) : seuls les champs renseignes sont fixes ; le DN,
                # s'il n'est pas force, reste plafonne par `dn_ceiling` (continuite vers l'aval,
                # comme le dimensionnement automatique ci-dessous).
                min_di = min_di_mm_for_velocity(seg.flow_m3s, seg.max_velocity_ms)
                max_di = max_di_mm_for_velocity(seg.flow_m3s, seg.min_velocity_ms)
                material_fn = _partial_forced_material_fn(seg.forced_material, allowed_materials_fn)
                effective_dn_max = seg.forced_dn if seg.forced_dn is not None else dn_ceiling
                candidates = _candidates(
                    catalog, min_di, seg.forced_dn, effective_dn_max, material_fn, min_pms_needed, max_di,
                    exact_pressure_class=seg.forced_pressure_class,
                )
                if not candidates and effective_dn_max is not None and seg.forced_dn is None:
                    # Le plafond de telescopage n'est pas atteignable avec ce materiau/cette classe
                    # (ex. un materiau dont le plus petit DN au catalogue depasse le plafond etabli
                    # en amont) — on relache le plafond plutot que d'aller directement au repli
                    # suivant (qui, lui, ignore aussi vitesse/PMS) : cf. le meme raisonnement cote
                    # gravitaire (solve_gravitaire_troncon, consigne utilisateur : "le choix des DN
                    # ne respecte pas le téléscopage").
                    candidates = _candidates(
                        catalog, min_di, seg.forced_dn, None, material_fn, min_pms_needed, max_di,
                        exact_pressure_class=seg.forced_pressure_class,
                    )
                    if candidates and attempt == _MAX_REFOULEMENT_PMS_ITERATIONS:
                        alerts.append(
                            f"{seg_label} : le plafond de télescopage (DN {effective_dn_max}) n'est pas "
                            f"atteignable avec la contrainte matériau/classe imposée — DN choisi "
                            f"librement pour cette contrainte, télescopage non respecté ici."
                        )
                if not candidates:
                    candidates = _candidates(
                        catalog, 0.0, seg.forced_dn, None, material_fn, 0.0, math.inf,
                        exact_pressure_class=seg.forced_pressure_class,
                    )
                    if candidates:
                        if attempt == _MAX_REFOULEMENT_PMS_ITERATIONS:
                            alerts.append(
                                f"{seg_label} : la contrainte partielle imposée ne permet de respecter "
                                f"ni la vitesse ni le PMS requis — conduite retenue malgré tout, alerte "
                                f"informative."
                            )
                    else:
                        if attempt == _MAX_REFOULEMENT_PMS_ITERATIONS:
                            alerts.append(
                                f"{seg_label} : aucune conduite active ne correspond à la contrainte "
                                f"partielle imposée — vérifier la fenêtre Conduites."
                            )
                        candidates = _candidates(catalog, 0.0, None, None, None) or list(catalog)
                cand = candidates[0]
            else:
                min_di = min_di_mm_for_velocity(seg.flow_m3s, seg.max_velocity_ms)
                max_di = max_di_mm_for_velocity(seg.flow_m3s, seg.min_velocity_ms)
                candidates = _candidates(
                    catalog, min_di, None, dn_ceiling, allowed_materials_fn, min_pms_needed, max_di
                )
                if not candidates:
                    if attempt == _MAX_REFOULEMENT_PMS_ITERATIONS:
                        alerts.append(
                            f"{seg_label} : aucune conduite active ne respecte vitesse/PMS/matériaux "
                            f"autorisés (DN plafonné à {dn_ceiling}) — vérifier le catalogue Conduites."
                        )
                    candidates = _candidates(catalog, 0.0, None, dn_ceiling, None) or list(catalog)
                cand = candidates[0]
            velocity, j = segment_hydraulics(seg.flow_m3s, cand.di_mm, cand.roughness_mm, viscosity)
            if seg.forced_dn is not None:
                if seg.max_velocity_ms and velocity > seg.max_velocity_ms + 1e-6:
                    alerts.append(
                        f"{seg_label} : vitesse {velocity:.2f} m/s supérieure à la vitesse max "
                        f"({seg.max_velocity_ms:.2f} m/s) pour le DN {seg.forced_dn} forcé — calcul "
                        f"effectué malgré la contrainte matériau/DN forcée."
                    )
                if seg.min_velocity_ms and velocity < seg.min_velocity_ms - 1e-6:
                    alerts.append(
                        f"{seg_label} : vitesse {velocity:.2f} m/s inférieure à la vitesse min "
                        f"({seg.min_velocity_ms:.2f} m/s) pour le DN {seg.forced_dn} forcé — calcul "
                        f"effectué malgré la contrainte matériau/DN forcée."
                    )
            prelim.append((seg, cand, velocity, j))
            # Ne JAMAIS laisser le plafond AUGMENTER (meme raisonnement que dn_floor cote
            # gravitaire, cf. solve_gravitaire_troncon — consigne utilisateur : "le choix des DN
            # ne respecte pas le téléscopage") — une contrainte forcee/partielle peut retenir un DN
            # plus GRAND que le plafond deja etabli en amont ; le laisser ecraser `dn_ceiling`
            # laisserait les segments libres ENCORE plus en aval regonfler au-dela de ce que le
            # telescopage avait deja resserre. Pour la branche libre, `cand.dn` est deja <=
            # `dn_ceiling` par construction (passe en `dn_max` a `_candidates`) : ce min est donc
            # un no-op pour elle, et ne resserre le plafond QUE si la contrainte forcee a
            # elle-meme choisi plus petit (telescopage qui continue normalement apres elle).
            dn_ceiling = cand.dn if dn_ceiling is None else min(dn_ceiling, cand.dn)

        # Perte cumulee depuis le DEBUT du troncon (amont), noeud par noeud — la cote de depart H0
        # n'est pas encore fixee, seule cette perte l'est (elle ne depend que des DN choisis ci-dessus).
        cumulative_by_node = {node_ids_ordered[0]: 0.0}
        losses: list[float] = []
        running_loss = 0.0
        for i, (seg, cand, velocity, j) in enumerate(prelim):
            loss = j * seg.length_m * (1 + singular_loss_markup_pct / 100)
            losses.append(loss)
            running_loss += loss
            cumulative_by_node[node_ids_ordered[i + 1]] = running_loss

        # H0 = plus petite cote de depart telle que, pour CHAQUE noeud exigeant une pression
        # minimale, H0 - perte_cumulee(noeud) - z(noeud) >= exigence(noeud) — forme close de
        # "augmenter H0 jusqu'a ce que ca marche partout" (consigne utilisateur). Les noeuds de la
        # zone d'exclusion (Preferences, consigne utilisateur) n'influencent jamais H0 — deja
        # retires de `required_by_node` (cf. _required_pressure_by_node), verifies a part plus bas.
        h0 = 0.0
        for nid, required in required_by_node.items():
            h0 = max(h0, required + cumulative_by_node[nid] + node_ground_z[nid])

        # Meme principe pour CHAQUE point echantillonne du profil de terrain (pas seulement les
        # noeuds reels, cf. docstring du module) : la perte cumulee y est interpolee lineairement
        # au sein du segment qui le contient (J constant sur un segment a DN fixe, donc exact). Les
        # points de la zone d'exclusion n'influencent pas non plus H0 — collectes a part pour la
        # verification informative une fois H0 connu (cf. plus bas).
        excluded_terrain_points = []
        if min_pressure is not None and terrain_samples and node_pk:
            for i, (seg, cand, velocity, j) in enumerate(prelim):
                pk_start = node_pk.get(node_ids_ordered[i])
                pk_end = node_pk.get(node_ids_ordered[i + 1])
                if pk_start is None or pk_end is None:
                    continue
                cum_start = cumulative_by_node[node_ids_ordered[i]]
                for pk, z in terrain_samples:
                    if pk < pk_start - 1e-6 or pk > pk_end + 1e-6:
                        continue
                    if exclusion_end_pk is not None and pk <= exclusion_end_pk + _EXCLUSION_ZONE_PK_EPSILON_M:
                        excluded_terrain_points.append(
                            (pk, cum_start + j * (pk - pk_start) * (1 + singular_loss_markup_pct / 100))
                        )
                        continue
                    cum_at_pk = cum_start + j * (pk - pk_start) * (1 + singular_loss_markup_pct / 100)
                    h0 = max(h0, min_pressure + cum_at_pk + z)

        nodes = {}
        for nid in node_ids_ordered:
            cote = h0 - cumulative_by_node[nid]
            nodes[nid] = NodeCalcResult(node_id=nid, piezo_head=cote, pressure_dynamic=cote - node_ground_z[nid])

        # La classe retenue pour chaque segment doit couvrir la pression DYNAMIQUE qu'il verra
        # reellement (a ses deux extremites) — sinon on releve son plancher PMS et on refait un
        # tour complet (le nouveau choix peut changer le DI donc les pertes donc H0, cf. ci-dessus).
        bumped_any = False
        for i, (seg, cand, velocity, j) in enumerate(prelim):
            upstream_node = node_ids_ordered[i]
            downstream_node = node_ids_ordered[i + 1]
            max_pressure_seen = max(nodes[upstream_node].pressure_dynamic or 0.0, nodes[downstream_node].pressure_dynamic or 0.0)
            if cand.pms_m < max_pressure_seen - 1e-6 and max_pressure_seen > min_pms_by_segment.get(seg.id, 0.0) + 1e-6:
                min_pms_by_segment[seg.id] = max_pressure_seen
                bumped_any = True
        if not bumped_any or attempt == _MAX_REFOULEMENT_PMS_ITERATIONS:
            break

    alerts.extend(_check_excluded_nodes_pressure(node_ids_ordered, node_pk, nodes, min_pressure, excluded_node_ids))
    if min_pressure is not None and excluded_terrain_points:
        terrain_by_pk = dict(terrain_samples or [])
        excluded_terrain_violations = [
            (pk, h0 - cum_at_pk - terrain_by_pk[pk])
            for pk, cum_at_pk in excluded_terrain_points
            if pk in terrain_by_pk and (h0 - cum_at_pk - terrain_by_pk[pk]) < min_pressure - 1e-6
        ]
        if excluded_terrain_violations:
            worst_pressure = min(p for _, p in excluded_terrain_violations)
            pk_min = min(pk for pk, _ in excluded_terrain_violations)
            pk_max = max(pk for pk, _ in excluded_terrain_violations)
            alerts.append(
                f"{EXCLUSION_ZONE_ALERT_MARKER} : terrain sous la pression minimale entre PK {pk_min:.0f} m "
                f"et PK {pk_max:.0f} m ({len(excluded_terrain_violations)} point(s), pire cas "
                f"{worst_pressure:.1f} m pour {min_pressure:.1f} m requis) — dans la zone d'exclusion "
                f"(Préférences), alerte informative, calcul non bloqué."
            )

    results: list[SegmentCalcResult] = []
    running = 0.0
    for i, (seg, cand, velocity, j) in enumerate(prelim):
        loss = losses[i]
        running += loss
        upstream_node = node_ids_ordered[i]
        downstream_node = node_ids_ordered[i + 1]
        max_pressure_seen = max(nodes[upstream_node].pressure_dynamic or 0.0, nodes[downstream_node].pressure_dynamic or 0.0)
        if cand.pms_m < max_pressure_seen - 1e-6:
            alerts.append(
                f"Segment entre {_node_label(upstream_node, node_pk)} et "
                f"{_node_label(downstream_node, node_pk)} : la pression de service "
                f"({max_pressure_seen:.1f} m) dépasse le PMS de la conduite retenue "
                f"({cand.pms_m:.1f} m) — matériau/classe à revoir."
            )
        results.append(
            SegmentCalcResult(
                id=seg.id, material=cand.material, pressure_class=cand.pressure_class, dn=cand.dn,
                di_mm=cand.di_mm, roughness_mm=cand.roughness_mm, flow_m3s=seg.flow_m3s,
                velocity_ms=velocity, head_loss_unit=j, head_loss_segment=loss, head_loss_cumulative=running,
            )
        )

    return TronconCalcResult(segments=results, nodes=[nodes[nid] for nid in node_ids_ordered], alerts=alerts)
