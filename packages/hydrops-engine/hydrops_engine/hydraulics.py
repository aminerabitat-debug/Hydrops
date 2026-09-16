"""Moteur de calcul hydraulique (bouton Calcul > Calculer, consigne utilisateur) — Lot 3 etape 2.

Fonctions pures operant sur des dataclasses simples, sans dependance a hydropack/FastAPI (meme
principe que topology/network.py : "moteur pur, sans effet de bord", l'appelant cote API convertit
les modeles pydantic vers/depuis ces types avant/apres l'appel).

Approche retenue (3e iteration, validee avec l'utilisateur) — les deux regimes sont CALCULES EN
SENS OPPOSE, parce que leur cote de depart n'a pas le meme statut physique :

  - Gravitaire : le niveau du reservoir amont est une donnee FIXE (la nature, pas un choix de
    conception) — on ne peut pas "l'augmenter" pour rattraper un manque de pression en route. On
    parcourt donc le troncon AMONT -> AVAL, en 4 phases :
      1. Dimensionnement initial, PIQUET PAR PIQUET, INDEPENDAMMENT (aucun plancher/telescopage a
         ce stade) : le DN est choisi sur la seule vitesse max (`_resolve_piquet_pipe`) ; si le
         materiau a un DI qui depend de la classe, la classe est choisie sur la seule pression
         HYDROSTATIQUE locale (`pressure_static_max`, niveau reservoir max — sans ecoulement),
         puisqu'elle seule determine alors le DI utilise par le calcul hydraulique ; sinon la
         classe n'a aucun impact hydraulique et n'a pas besoin d'etre fixee a ce stade. Un segment
         sous contrainte (materiau/DN/classe force, ex. homogeneisation) est resolu EXACTEMENT tel
         quel (`_resolve_forced_pipe`), jamais reevalue.
      2. Ligne piezometrique, AMONT -> AVAL : cote du 1er piquet = niveau reservoir (donnee fixe,
         AUCUNE translation necessaire), chaque segment retranchant ensuite sa perte de charge.
      3. Identification des piquets en violation (noeuds reels ET points de terrain
         echantillonnes, cf. ci-dessous) par rapport a `min_pressure`/`downstream_residual_pressure`.
      4. Reparation : s'il reste des piquets en violation, on repart du TOUT PREMIER piquet du
         troncon et on augmente au palier catalogue superieur le premier segment LIBRE rencontre
         (jamais un segment sous contrainte) qui peut encore monter — un seul palier a la fois,
         on recalcule (localement : seul l'aval de ce segment se decale, cf. `_try_shrink_segment`
         pour le meme principe applique au retrecissement), on revalide, et on recommence sur ce
         MEME segment tant qu'il peut encore monter avant de passer au suivant — jusqu'a ce qu'il
         n'y ait plus de piquet en violation (alerte "pression minimale non garantie" sinon).
    Ce decoupage evite tout mecanisme de plancher/translation implicite (chaque piquet est
    dimensionne seul en Phase 1 ; seule la Phase 4, explicite, augmente un DN) — une fois une
    solution sans alerte obtenue, l'optimisation telescopique (reduction du DN par paliers,
    aval -> amont, cf. plus bas) s'applique EXACTEMENT comme avant, inchangee. Les cotes/pressions
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
  - Gravitaire, augmentation iterative du DN (Phase 4, consigne utilisateur) : quand la pression
    minimale n'est pas tenue quelque part (noeud ou point de terrain), on repart du TOUT PREMIER
    piquet du troncon et on augmente au palier superieur le premier segment LIBRE rencontre qui
    peut encore monter (jamais un segment sous contrainte) — un seul a la fois, recalcule
    localement (aucune repasse complete necessaire, cf. `solve_gravitaire_troncon`), jusqu'a ce
    qu'il n'y ait plus de piquet en violation. Cette augmentation ne va jamais au-dela du DN qui
    ferait tomber la vitesse sous la vitesse min (meme plafond que ci-dessus) : au-dela, l'alerte
    "pression insuffisante" persiste plutot que de continuer a grossir indefiniment.
  - Darcy-Weisbach + Colebrook-White (resolution iterative, pas d'approximation) pour la perte de
    charge lineaire unitaire ; regime laminaire (Re<2300) via f=64/Re. Majoration (%) appliquee a
    la perte lineaire pour approcher les pertes de charge singulieres (Preferences).
"""

from __future__ import annotations

import bisect
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


def _terrain_violations(
    node_ids_ordered: list[str],
    node_pk: Optional[dict[str, float]],
    node_cotes: dict[str, float],
    min_pressure: Optional[float],
    terrain_samples: Optional[list[tuple[float, float]]],
    exclusion_end_pk: Optional[float] = None,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Coeur du controle terrain (cf. `_check_terrain_pressure`, qui en derive les alertes) :
    calcule, pour CHAQUE point echantillonne du profil, la pression obtenue par interpolation
    lineaire de la cote piezometrique entre les deux piquets encadrants — reutilise par le
    bouclage AMONT du dimensionnement de base (cf. solve_gravitaire_troncon) pour savoir QUEL
    segment augmenter quand un point de terrain (pas seulement un noeud reel) manque de pression,
    en plus de la construction des alertes agregees. Retourne (violations, violations_exclues)."""
    if min_pressure is None or not terrain_samples or not node_pk:
        return [], []
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
    return violations, excluded_violations


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
    violations, excluded_violations = _terrain_violations(
        node_ids_ordered, node_pk, node_cotes, min_pressure, terrain_samples, exclusion_end_pk
    )
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


def _resolve_piquet_pipe(
    seg: SegmentSpec,
    catalog: list[CatalogPipe],
    allowed_materials_fn: Optional[AllowedMaterialsFn],
    min_di: float,
    max_di: float,
    max_pms_needed: float,
    seg_label: str,
) -> tuple[CatalogPipe, list[str]]:
    """Resout la conduite d'UN piquet, INDEPENDAMMENT de tous les autres (Phase 1 du gravitaire,
    cf. docstring module) : aucun plancher de telescopage ici (chaque piquet est resolu seul, sans
    thread amont/aval — seule la Phase 4, explicite, augmente un DN apres coup). Contrainte
    complete (materiau+DN, ex. homogeneisation) -> resolution catalogue EXACTE
    (`_resolve_forced_pipe`, le DI peut alors varier avec la classe pour les materiaux ou elle en
    depend). Contrainte partielle (un seul champ, ou seule la classe) -> seuls les champs
    renseignes sont fixes, le reste choisi automatiquement. Libre -> le moins cher respectant
    vitesse/PMS/materiaux autorises. Retourne (pipe, alerts) ; n'ajoute PAS l'alerte de vitesse
    pour un DN force (a la charge de l'appelant, qui a besoin de la vitesse effective — connue
    seulement apres ce choix)."""
    if seg.forced_material is not None and seg.forced_dn is not None:
        # Materiau/DN forces (consigne utilisateur) : plus d'auto-dimensionnement pour ce segment.
        # Si une classe est EN PLUS forcee (homogeneisation), elle est retenue exactement telle
        # quelle (cf. _resolve_forced_pipe) ; sinon la moins chere disponible est retenue
        # automatiquement. Le calcul s'applique meme si le PMS/la vitesse n'est pas respecte
        # (alerte informative, jamais bloquante contrairement au dimensionnement automatique).
        cand, pms_ok = _resolve_forced_pipe(
            catalog, seg.forced_material, seg.forced_dn, max_pms_needed, seg.forced_pressure_class
        )
        if cand is None:
            class_suffix = f" {seg.forced_pressure_class}" if seg.forced_pressure_class else ""
            fallback = _candidates(catalog, 0.0, None, None, None) or list(catalog)
            return fallback[0], [
                f"{seg_label} : aucune conduite active {seg.forced_material} DN{seg.forced_dn}"
                f"{class_suffix} au catalogue — vérifier la fenêtre Conduites."
            ]
        if not pms_ok:
            return cand, [
                f"{seg_label} : le DN {seg.forced_dn} force en {seg.forced_material} ne respecte pas "
                f"le PMS requis ({max_pms_needed:.1f} m, classe {cand.pressure_class} = {cand.pms_m:.1f} m) "
                f"— calcul effectué malgré la contrainte matériau/DN forcée."
            ]
        return cand, []
    if seg.forced_material is not None or seg.forced_dn is not None or seg.forced_pressure_class is not None:
        # Contrainte PARTIELLE (materiau et/ou DN et/ou classe — consigne utilisateur, contraintes
        # par plage de PK) : seuls les champs renseignes sont fixes, le reste est choisi
        # automatiquement (le moins cher respectant vitesse/PMS/materiaux autorises parmi ce qui
        # reste). Pas de plancher de telescopage ici (Phase 1, aucun thread amont/aval) : si le DN
        # lui-meme n'est pas force, il est choisi librement (sans plancher), contrairement a
        # l'ancienne conception aval->amont qui devait en preserver un pour ne pas creer
        # d'etranglement local — ce risque n'existe plus, chaque piquet etant deja independant.
        material_fn = _partial_forced_material_fn(seg.forced_material, allowed_materials_fn)
        candidates = _candidates(
            catalog, min_di, seg.forced_dn, seg.forced_dn, material_fn, max_pms_needed, max_di,
            exact_pressure_class=seg.forced_pressure_class,
        )
        if candidates:
            return candidates[0], []
        candidates = _candidates(
            catalog, 0.0, None, seg.forced_dn, material_fn, 0.0, math.inf,
            exact_pressure_class=seg.forced_pressure_class,
        )
        if candidates:
            return candidates[0], [
                f"{seg_label} : la contrainte partielle imposée ne permet de respecter ni la "
                f"vitesse ni le PMS requis — conduite retenue malgré tout, alerte informative."
            ]
        fallback = _candidates(catalog, 0.0, None, None, None) or list(catalog)
        return fallback[0], [
            f"{seg_label} : aucune conduite active ne correspond à la contrainte partielle "
            f"imposée — vérifier la fenêtre Conduites."
        ]
    candidates = _candidates(catalog, min_di, None, None, allowed_materials_fn, max_pms_needed, max_di)
    if candidates:
        return candidates[0], []
    fallback = _candidates(catalog, 0.0, None, None, None) or list(catalog)
    return fallback[0], [
        f"{seg_label} : aucune conduite active ne respecte vitesse/PMS/matériaux autorisés "
        f"— vérifier le catalogue Conduites."
    ]


def _terrain_violations_indexed(
    node_ids_ordered: list[str],
    node_pk: dict[str, float],
    node_cotes: dict[str, float],
    min_pressure: float,
    terrain_samples: list[tuple[float, float]],
    exclusion_end_pk: Optional[float],
) -> list[tuple[float, float, int]]:
    """Comme `_terrain_violations` (violations reelles uniquement, zone d'exclusion toujours
    toleree) mais fusionne en un seul passage (O(N+M), meme technique que `_terrain_ok_from` —
    `node_ids_ordered` ET `terrain_samples` sont tous deux ordonnes par PK croissant) et annote
    chaque violation de l'INDICE du segment qui l'encadre. Utilise par la Phase 4 (reparation) de
    `solve_gravitaire_troncon` : cet indice permet de revalider un point precis en O(1) (cotes des
    2 noeuds encadrants deja connues) apres un ajustement local du DN, sans reparcourir
    `terrain_samples` a chaque tentative."""
    violations: list[tuple[float, float, int]] = []
    ts_idx = 0
    total = len(terrain_samples)
    for k in range(len(node_ids_ordered) - 1):
        a, b = node_ids_ordered[k], node_ids_ordered[k + 1]
        pk_a, pk_b = node_pk[a], node_pk[b]
        cote_a, cote_b = node_cotes[a], node_cotes[b]
        span = pk_b - pk_a
        while ts_idx < total and terrain_samples[ts_idx][0] <= pk_b + 1e-6:
            pk, z = terrain_samples[ts_idx]
            ts_idx += 1
            if pk < pk_a - 1e-6:
                continue
            t = 0.0 if span <= 1e-9 else (pk - pk_a) / span
            cote = cote_a + t * (cote_b - cote_a)
            pressure = cote - z
            if pressure < min_pressure - 1e-6:
                if exclusion_end_pk is None or pk > exclusion_end_pk + _EXCLUSION_ZONE_PK_EPSILON_M:
                    violations.append((pk, z, k))
    return violations


def _terrain_ok_from(
    node_ids_ordered: list[str],
    node_pk: dict[str, float],
    node_cotes: dict[str, float],
    start_i: int,
    min_pressure: float,
    terrain_samples: list[tuple[float, float]],
    exclusion_end_pk: Optional[float],
) -> bool:
    """Equivalent de `_check_terrain_pressure` (violations reelles seulement, zone d'exclusion
    toujours toleree) mais limite aux piquets d'indice >= start_i ET en un seul passage fusionne
    (node_ids_ordered ET terrain_samples sont tous deux ordonnes par PK croissant) — O(N-start_i +
    M) au lieu de O((N-start_i) x M) pour `_check_terrain_pressure`, qui reteste tout
    `terrain_samples` a chaque paire de noeuds. Utilise par `_try_shrink_segment` (telescopage,
    consigne utilisateur : ne revalider que l'AVAL du piquet modifie) ou` le nombre d'essais rend ce
    cout quadratique-en-M critique. `terrain_samples` DOIT deja etre restreint a pk >=
    node_pk[node_ids_ordered[start_i]] (cf. bisect au point d'appel) pour que le pointeur demarre
    au bon endroit."""
    ts_idx = 0
    total = len(terrain_samples)
    for k in range(start_i, len(node_ids_ordered) - 1):
        a, b = node_ids_ordered[k], node_ids_ordered[k + 1]
        pk_a, pk_b = node_pk[a], node_pk[b]
        cote_a, cote_b = node_cotes[a], node_cotes[b]
        span = pk_b - pk_a
        while ts_idx < total and terrain_samples[ts_idx][0] <= pk_b + 1e-6:
            pk, z = terrain_samples[ts_idx]
            ts_idx += 1
            if pk < pk_a - 1e-6:
                continue
            t = 0.0 if span <= 1e-9 else (pk - pk_a) / span
            cote = cote_a + t * (cote_b - cote_a)
            pressure = cote - z
            if pressure < min_pressure - 1e-6:
                if exclusion_end_pk is None or pk > exclusion_end_pk + _EXCLUSION_ZONE_PK_EPSILON_M:
                    return False
    return True


def _try_shrink_segment(
    node_ids_ordered: list[str],
    segments_ordered: list[SegmentSpec],
    catalog: list[CatalogPipe],
    singular_loss_markup_pct: float,
    viscosity: float,
    allowed_materials_fn: Optional[AllowedMaterialsFn],
    node_pk: Optional[dict[str, float]],
    min_pressure: Optional[float],
    terrain_samples: Optional[list[tuple[float, float]]],
    exclusion_end_pk: Optional[float],
    required_by_node: dict[str, float],
    nodes: dict[str, NodeCalcResult],
    results: list[SegmentCalcResult],
    i: int,
    trial_dn: int,
) -> bool:
    """Coeur de l'optimisation telescopique (consigne utilisateur) : tente de reduire UNIQUEMENT le
    segment `i` a `trial_dn`, sans jamais retoucher le catalogue ni la cote des piquets en AMONT de
    lui (indices <= i) — mathematiquement inchanges, quel que soit le DN retenu pour `i` : la ligne
    piezometrique part du reservoir (cote fixe, cf. Phase 2 de `solve_gravitaire_troncon`) et se
    construit AMONT -> AVAL, donc tout ce qui se trouve ENTRE le reservoir et le piquet modifie reste
    par construction identique. Seule la cote (et donc la pression) des piquets STRICTEMENT EN AVAL
    de `i` se decale d'une meme constante `delta` (la variation de perte de charge du seul segment `i`) — ce sont eux,
    et EUX SEULS, qui sont revalides ici, jusqu'a la fin du tronçon (consigne utilisateur). Mute
    `nodes`/`results` EN PLACE si le palier est accepte ; les laisse rigoureusement inchanges sinon
    (aucune mutation partielle en cas de rejet). Retourne True si accepte."""
    seg = segments_ordered[i]
    upstream_node = node_ids_ordered[i]
    downstream_node = node_ids_ordered[i + 1]
    max_pms_needed = max(
        nodes[upstream_node].pressure_static_max or 0.0,
        nodes[downstream_node].pressure_static_max or 0.0,
    )
    min_di = min_di_mm_for_velocity(seg.flow_m3s, seg.max_velocity_ms)
    max_di = max_di_mm_for_velocity(seg.flow_m3s, seg.min_velocity_ms)
    candidates = _candidates(catalog, min_di, trial_dn, trial_dn, allowed_materials_fn, max_pms_needed, max_di)
    if not candidates:
        # Meme situation que l'ancien `trial_alerts` non vide (aucune conduite active a ce DN
        # respectant vitesse/PMS/materiaux autorises) — rejet, comme avant.
        return False
    cand = candidates[0]
    velocity, j = segment_hydraulics(seg.flow_m3s, cand.di_mm, cand.roughness_mm, viscosity)
    new_loss = j * seg.length_m * (1 + singular_loss_markup_pct / 100)
    delta = new_loss - results[i].head_loss_segment

    # Piquets strictement en aval (indices > i) : cote/pression se decalent de -delta — jamais leur
    # conduite (deja figee, aucune recherche catalogue pour eux ici). Verifie AUSSI (avant tout
    # commit) qu'aucun ne passe sous sa pression minimale requise.
    shifted_piezo: dict[str, float] = {}
    for k in range(i + 1, len(node_ids_ordered)):
        nid = node_ids_ordered[k]
        shifted_piezo[nid] = nodes[nid].piezo_head - delta
        required = required_by_node.get(nid)
        if required is not None and (nodes[nid].pressure_dynamic or 0.0) - delta < required - 1e-6:
            return False

    # Meme verification, mais sur CHAQUE point de terrain echantillonne entre le piquet modifie et
    # la fin du tronçon (consigne utilisateur) — pas seulement les noeuds reels ci-dessus.
    if min_pressure is not None and terrain_samples and node_pk:
        start_pk = node_pk.get(upstream_node)
        start_ts = bisect.bisect_left(terrain_samples, start_pk, key=lambda t: t[0]) if start_pk is not None else 0
        node_cotes = {upstream_node: nodes[upstream_node].piezo_head, **shifted_piezo}
        if not _terrain_ok_from(
            node_ids_ordered, node_pk, node_cotes, i, min_pressure,
            terrain_samples[start_ts:], exclusion_end_pk,
        ):
            return False

    # Accepte : commit en place, uniquement sur `i` et l'aval.
    for k in range(i + 1, len(node_ids_ordered)):
        nid = node_ids_ordered[k]
        n = nodes[nid]
        nodes[nid] = replace(n, piezo_head=shifted_piezo[nid], pressure_dynamic=(n.pressure_dynamic or 0.0) - delta)
    results[i] = replace(
        results[i], material=cand.material, pressure_class=cand.pressure_class, dn=cand.dn,
        di_mm=cand.di_mm, roughness_mm=cand.roughness_mm, velocity_ms=velocity,
        head_loss_unit=j, head_loss_segment=new_loss,
    )
    for k in range(i, len(results)):
        results[k] = replace(results[k], head_loss_cumulative=results[k].head_loss_cumulative + delta)
    return True


# Garde-fou anti-boucle infinie pour la Phase 4 (augmentation iterative de DN) ci-dessous —
# compte desormais des PALIERS INDIVIDUELS (un seul segment, un seul palier a la fois, cf.
# docstring module) et non plus des passes completes comme avant : chaque palier est une operation
# locale bon marche (O(1) + O(violations restantes), plus la repasse complete O(N) d'autrefois),
# donc un plafond largement plus genereux reste peu couteux meme s'il est atteint (consigne
# utilisateur : "processus iteratif", imperfection acceptee au-dela de ce plafond). La convergence
# est de toute facon garantie par la finitude du catalogue (chaque segment ne peut monter qu'un
# nombre fini de paliers avant qu'aucun palier plus grand ne convienne).
_MAX_GRAVITAIRE_DN_BUMP_ITERATIONS = 2000

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
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> TronconCalcResult:
    """Gravitaire, sens AMONT -> AVAL en 4 phases (cf. docstring du module) : le niveau du
    reservoir est une donnee fixe, pas un choix de conception. `upstream_level_min` peut etre
    `None` (niveau pas encore renseigne dans "Modifier le tronçon") : le pre-check hydrostatique
    est alors simplement desactive, le reste du calcul utilise 0.0 comme avant (comportement
    inchange pour un appelant qui passait deja un float). Si la pression minimale n'est pas tenue
    quelque part, la Phase 4 augmente au palier superieur le premier segment LIBRE rencontre en
    repartant du debut du tronçon (consigne utilisateur), un seul a la fois, avant de se resoudre a
    alerter. `on_progress(done, total)`, si fourni, est appele au fil du calcul (jamais par palier
    de DN candidat lors des Phases 1/4 ou du telescopage — trop frequent) — toujours appele une
    derniere fois avec `done == total` avant de rendre la main, quel que soit le chemin emprunte
    (consigne utilisateur : barre de progression a pourcentage reel, cf.
    network.py:run_calculation). Callback synchrone, sans effet sur le resultat — le moteur reste
    pur (aucun I/O/asyncio)."""
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
        if on_progress is not None:
            on_progress(1, 1)
        return TronconCalcResult(segments=[], nodes=reset_nodes, alerts=hydrostatic_alerts)

    progress_total = 3 + len(segments_ordered)
    viscosity = kinematic_viscosity_m2s(fluid_temperature_c)
    exclusion_end_pk = _exclusion_zone_end_pk(
        node_pk, node_ids_ordered[0], node_ids_ordered[-1], min_pressure_exclusion_m
    )
    required_by_node, excluded_node_ids = _required_pressure_by_node(
        node_ids_ordered, min_pressure, downstream_residual_pressure, node_pk, exclusion_end_pk
    )

    # Pressions HYDROSTATIQUES (sans ecoulement, niveau constant) : purement geometriques, donc
    # calculables une fois pour toutes, independamment des Phases 1-4 qui suivent.
    pressure_static_max = {nid: upstream_level_max - node_ground_z[nid] for nid in node_ids_ordered}
    pressure_static_min = {nid: effective_upstream_level_min - node_ground_z[nid] for nid in node_ids_ordered}

    def _is_forced(seg: SegmentSpec) -> bool:
        return seg.forced_material is not None or seg.forced_dn is not None or seg.forced_pressure_class is not None

    # --- Phase 1 : dimensionnement initial, PIQUET PAR PIQUET, independamment (cf. docstring
    # module) — aucun plancher/thread amont-aval a ce stade.
    results: list[SegmentCalcResult] = []
    pass_alerts: list[str] = []
    for i, seg in enumerate(segments_ordered):
        upstream_node = node_ids_ordered[i]
        downstream_node = node_ids_ordered[i + 1]
        min_di = min_di_mm_for_velocity(seg.flow_m3s, seg.max_velocity_ms)
        max_di = max_di_mm_for_velocity(seg.flow_m3s, seg.min_velocity_ms)
        max_pms_needed = max(pressure_static_max[upstream_node], pressure_static_max[downstream_node])
        seg_label = f"Segment entre {_node_label(upstream_node, node_pk)} et {_node_label(downstream_node, node_pk)}"
        cand, seg_alerts = _resolve_piquet_pipe(seg, catalog, allowed_materials_fn, min_di, max_di, max_pms_needed, seg_label)
        pass_alerts.extend(seg_alerts)
        velocity, j = segment_hydraulics(seg.flow_m3s, cand.di_mm, cand.roughness_mm, viscosity)
        if seg.forced_dn is not None:
            if seg.max_velocity_ms and velocity > seg.max_velocity_ms + 1e-6:
                pass_alerts.append(
                    f"{seg_label} : vitesse {velocity:.2f} m/s supérieure à la vitesse max "
                    f"({seg.max_velocity_ms:.2f} m/s) pour le DN {seg.forced_dn} forcé — calcul "
                    f"effectué malgré la contrainte matériau/DN forcée."
                )
            if seg.min_velocity_ms and velocity < seg.min_velocity_ms - 1e-6:
                pass_alerts.append(
                    f"{seg_label} : vitesse {velocity:.2f} m/s inférieure à la vitesse min "
                    f"({seg.min_velocity_ms:.2f} m/s) pour le DN {seg.forced_dn} forcé — calcul "
                    f"effectué malgré la contrainte matériau/DN forcée."
                )
        loss = j * seg.length_m * (1 + singular_loss_markup_pct / 100)
        results.append(
            SegmentCalcResult(
                id=seg.id, material=cand.material, pressure_class=cand.pressure_class, dn=cand.dn,
                di_mm=cand.di_mm, roughness_mm=cand.roughness_mm, flow_m3s=seg.flow_m3s,
                velocity_ms=velocity, head_loss_unit=j, head_loss_segment=loss, head_loss_cumulative=0.0,
            )
        )
    if on_progress is not None:
        on_progress(1, progress_total)

    # --- Phase 2 : ligne piezometrique AMONT -> AVAL — cote du 1er piquet = niveau reservoir
    # (donnee fixe), AUCUNE translation necessaire (cf. docstring module).
    nodes: dict[str, NodeCalcResult] = {}
    first_node = node_ids_ordered[0]
    piezo = effective_upstream_level_min
    nodes[first_node] = NodeCalcResult(
        node_id=first_node, piezo_head=piezo, pressure_dynamic=piezo - node_ground_z[first_node],
        pressure_static_max=pressure_static_max[first_node], pressure_static_min=pressure_static_min[first_node],
    )
    for i, seg in enumerate(segments_ordered):
        downstream_node = node_ids_ordered[i + 1]
        piezo -= results[i].head_loss_segment
        nodes[downstream_node] = NodeCalcResult(
            node_id=downstream_node, piezo_head=piezo, pressure_dynamic=piezo - node_ground_z[downstream_node],
            pressure_static_max=pressure_static_max[downstream_node], pressure_static_min=pressure_static_min[downstream_node],
        )
    running = 0.0
    for idx, r in enumerate(results):
        running += r.head_loss_segment
        results[idx] = replace(r, head_loss_cumulative=running)
    if on_progress is not None:
        on_progress(2, progress_total)

    # Le reservoir amont lui-meme ne peut fournir plus que sa cote MINIMALE garantie : si celle-ci,
    # a PERTE DE CHARGE NULLE (le meilleur cas possible, DI infini), ne suffit deja pas a satisfaire
    # l'exigence d'un piquet, aucun dimensionnement ne peut jamais y remedier (consigne
    # utilisateur) — signale distinctement du deficit "pression insuffisante" generique ci-dessous,
    # qui LUI peut encore etre resolu par la Phase 4.
    reservoir_shortfall: Optional[tuple[str, float]] = None
    for nid, required in required_by_node.items():
        shortfall = required - (effective_upstream_level_min - node_ground_z[nid])
        if shortfall > 1e-6 and (reservoir_shortfall is None or shortfall > reservoir_shortfall[1]):
            reservoir_shortfall = (nid, shortfall)

    # --- Phase 3 : identification des piquets en violation (noeuds reels ET points de terrain
    # echantillonnes, cf. docstring module).
    node_index = {nid: idx for idx, nid in enumerate(node_ids_ordered)}
    violating_nodes = [
        nid for nid, required in required_by_node.items()
        if (nodes[nid].pressure_dynamic or 0.0) < required - 1e-6
    ]
    terrain_violations_idx: list[tuple[float, float, int]] = []
    if min_pressure is not None and terrain_samples and node_pk:
        terrain_violations_idx = _terrain_violations_indexed(
            node_ids_ordered, node_pk, {nid: nodes[nid].piezo_head for nid in node_ids_ordered},
            min_pressure, terrain_samples, exclusion_end_pk,
        )

    # --- Phase 4 : reparation — on repart du tout premier piquet du tronçon et on augmente au
    # palier superieur le premier segment LIBRE rencontre qui peut encore monter, un seul a la
    # fois, en revalidant localement (cf. `_try_shrink_segment` pour le meme principe applique au
    # retrecissement — seul l'AVAL du segment modifie change, jamais l'amont, la cote du reservoir
    # etant fixe des le depart). Bornee par un plafond de securite anti-boucle infinie (le meme que
    # l'ancien mecanisme) meme si la convergence est en pratique garantie par la finitude du
    # catalogue (chaque segment ne peut monter qu'un nombre fini de paliers).
    dn_by_segment_id = {r.id: r.dn for r in results}
    pointer = 0
    bump_steps = 0
    while (violating_nodes or terrain_violations_idx) and bump_steps < _MAX_GRAVITAIRE_DN_BUMP_ITERATIONS:
        # Aucun segment strictement en amont d'une violation ne peut plus l'aider au-dela de cette
        # borne (Phase 4 ne cherche jamais plus loin) — se retrecit au fil des violations resolues.
        upper_bound = -1
        for nid in violating_nodes:
            upper_bound = max(upper_bound, node_index[nid] - 1)
        for _pk, _z, seg_idx in terrain_violations_idx:
            upper_bound = max(upper_bound, seg_idx)
        if pointer > upper_bound:
            break
        seg = segments_ordered[pointer]
        if _is_forced(seg):
            pointer += 1
            continue
        upstream_node = node_ids_ordered[pointer]
        downstream_node = node_ids_ordered[pointer + 1]
        min_di = min_di_mm_for_velocity(seg.flow_m3s, seg.max_velocity_ms)
        max_di = max_di_mm_for_velocity(seg.flow_m3s, seg.min_velocity_ms)
        max_pms_needed = max(pressure_static_max[upstream_node], pressure_static_max[downstream_node])
        current_dn = dn_by_segment_id[seg.id]
        candidates = _candidates(catalog, min_di, current_dn + 1, None, allowed_materials_fn, max_pms_needed, max_di)
        if not candidates:
            pointer += 1
            continue
        bump_steps += 1
        cand = candidates[0]
        velocity, j = segment_hydraulics(seg.flow_m3s, cand.di_mm, cand.roughness_mm, viscosity)
        new_loss = j * seg.length_m * (1 + singular_loss_markup_pct / 100)
        delta = new_loss - results[pointer].head_loss_segment  # <= 0 : la perte diminue ou reste egale
        for k in range(pointer + 1, len(node_ids_ordered)):
            nid = node_ids_ordered[k]
            n = nodes[nid]
            nodes[nid] = replace(n, piezo_head=n.piezo_head - delta, pressure_dynamic=(n.pressure_dynamic or 0.0) - delta)
        results[pointer] = replace(
            results[pointer], material=cand.material, pressure_class=cand.pressure_class, dn=cand.dn,
            di_mm=cand.di_mm, roughness_mm=cand.roughness_mm, velocity_ms=velocity,
            head_loss_unit=j, head_loss_segment=new_loss,
        )
        for k in range(pointer, len(results)):
            results[k] = replace(results[k], head_loss_cumulative=results[k].head_loss_cumulative + delta)
        dn_by_segment_id[seg.id] = cand.dn

        violating_nodes = [nid for nid in violating_nodes if (nodes[nid].pressure_dynamic or 0.0) < required_by_node[nid] - 1e-6]
        still_terrain: list[tuple[float, float, int]] = []
        for pk, z, seg_idx in terrain_violations_idx:
            a, b = node_ids_ordered[seg_idx], node_ids_ordered[seg_idx + 1]
            pk_a, pk_b = node_pk[a], node_pk[b]
            span = pk_b - pk_a
            t = 0.0 if span <= 1e-9 else (pk - pk_a) / span
            cote = nodes[a].piezo_head + t * (nodes[b].piezo_head - nodes[a].piezo_head)
            if cote - z < min_pressure - 1e-6:
                still_terrain.append((pk, z, seg_idx))
        terrain_violations_idx = still_terrain

    if on_progress is not None:
        on_progress(3, progress_total)

    # Optimisation telescopique du diametre (consigne utilisateur, procedure validee explicitement) :
    # une fois une solution SANS aucune alerte obtenue (le DN "de base", le moins cher respectant
    # vitesse/PMS partout), on tente de la reduire par paliers catalogue successifs, en partant du
    # segment le plus AVAL et en remontant vers l'amont : DN(PK0) >= DN(fin de tronçon) doit
    # toujours etre respecte, donc chaque segment ne peut etre reduit qu'a un palier >= celui deja
    # retenu pour son voisin aval. Pour un segment donne, on retente le palier immediatement
    # inferieur et on accepte tant qu'aucune alerte n'apparait ; sinon on s'arrete pour ce segment
    # (il garde son dernier DN valide) et on passe au suivant, plus en amont. Les segments a
    # materiau/DN force (consigne utilisateur) ne sont jamais touches.
    #
    # Consigne utilisateur : reduire le DN d'un piquet ne doit revalider que l'AVAL de ce piquet,
    # jusqu'a la fin du tronçon — jamais l'amont, qui reste mathematiquement inchange quel que soit
    # le DN retenu ici (la translation finale cale toujours le reservoir exactement sur sa cote
    # fixee, donc tout ce qui separe le reservoir du piquet modifie n'en depend pas). `_try_shrink_
    # segment` fait exactement ca — un seul segment reresolu au catalogue, la portion aval decalee
    # d'une constante et revalidee (noeuds + terrain), rien d'autre — remplace l'ancien recalcul
    # complet du tronçon (`_gravitaire_pass` + `_check_terrain_pressure` sur l'ensemble) qui
    # dominait le cout O(N^2) de cette boucle pour un tronçon a plusieurs milliers de piquets fins
    # (pleine resolution DEM, consigne utilisateur).
    if not violating_nodes and not pass_alerts:
        forced_dn_by_segment: dict[str, int] = {r.id: r.dn for r in results}
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
                accepted = _try_shrink_segment(
                    node_ids_ordered, segments_ordered, catalog, singular_loss_markup_pct, viscosity,
                    allowed_materials_fn, node_pk, min_pressure, terrain_samples, exclusion_end_pk,
                    required_by_node, nodes, results, i, trial_dn,
                )
                if not accepted:
                    break
                forced_dn_by_segment[seg.id] = trial_dn
            downstream_floor = forced_dn_by_segment[seg.id]
            if on_progress is not None:
                on_progress(3 + (len(segments_ordered) - i), progress_total)

    if on_progress is not None:
        on_progress(progress_total, progress_total)

    alerts = list(pass_alerts)
    if reservoir_shortfall is not None:
        _nid, shortfall = reservoir_shortfall
        alerts.append(
            f"{MIN_PRESSURE_ALERT_MARKER} : niveau du réservoir amont "
            f"({_node_label(node_ids_ordered[0], node_pk)}, min = {effective_upstream_level_min:.1f} m) "
            f"insuffisant de {shortfall:.1f} m pour garantir la pression minimale sur l'ensemble du "
            f"tronçon — revoir le découpage du tracé (brise-charge, tronçon plus court...)."
        )
    for nid in violating_nodes:
        actual = nodes[nid].pressure_dynamic or 0.0
        required = required_by_node[nid]
        alerts.append(
            f"{MIN_PRESSURE_ALERT_MARKER} : pression insuffisante au {_node_label(nid, node_pk)} "
            f"({actual:.1f} m obtenus, {required:.1f} m requis) — revoir le découpage du tracé "
            f"(brise-charge, tronçon plus court...)."
        )
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
    on_progress: Optional[Callable[[int, int], None]] = None,
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
    "silencieusement" acceptee au-dela de ce que la conduite supporte). `on_progress(done, total)`,
    si fourni, est appele une fois par tentative (pas de boucle de telescopage ici, cout lineaire) —
    toujours appele une derniere fois avec `done == total` avant de rendre la main (meme convention
    que solve_gravitaire_troncon)."""
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
        if on_progress is not None:
            on_progress(attempt + 1, _MAX_REFOULEMENT_PMS_ITERATIONS + 1)
        if not bumped_any or attempt == _MAX_REFOULEMENT_PMS_ITERATIONS:
            break

    if on_progress is not None:
        on_progress(_MAX_REFOULEMENT_PMS_ITERATIONS + 1, _MAX_REFOULEMENT_PMS_ITERATIONS + 1)

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
