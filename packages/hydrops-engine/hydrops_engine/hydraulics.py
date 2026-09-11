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
    # Contrainte Materiau/DN forcee (fenetre "Modifier le tronçon", consigne utilisateur) : ce
    # segment n'est plus auto-dimensionne (aucune recherche catalogue par vitesse/PMS, cf.
    # _resolve_forced_pipe) — la classe de pression la moins chere disponible pour ce (materiau,
    # DN) est retenue, et le calcul s'applique meme si la pression/vitesse resultante viole une
    # contrainte (alerte informative, jamais bloquante, contrairement au dimensionnement
    # automatique). Toujours ensemble : aucun sens a l'un sans l'autre.
    forced_material: Optional[str] = None
    forced_dn: Optional[int] = None


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
            and material_ok(p)
        ),
        key=lambda p: (p.price, p.dn, p.di_mm),
    )


def _resolve_forced_pipe(catalog: list[CatalogPipe], material: str, dn: int, min_pms_m: float) -> tuple[Optional[CatalogPipe], bool]:
    """Pour un (materiau, DN) force (consigne utilisateur, aucune classe de pression imposee) :
    retient la ligne active la moins chere satisfaisant `min_pms_m`, ou a defaut (aucune ne le
    respecte) la moins chere tout court — jamais un echec silencieux, le 2e element du tuple
    (`pms_ok`) indique si le PMS requis est effectivement tenu, a charge de l'appelant d'alerter
    si non. `None` si la combinaison n'existe meme pas dans le catalogue actif (ne devrait pas
    arriver, ecarte a la saisie cote API — cf. services/catalog.py:material_dn_exists)."""
    matches = [p for p in catalog if p.active and p.material == material and p.dn == dn]
    if not matches:
        return None, False
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


def _required_pressure_by_node(
    node_ids_ordered: list[str],
    min_pressure: Optional[float],
    downstream_residual_pressure: Optional[float],
) -> dict[str, float]:
    """`min_pressure` (si fourni) s'applique a tous les noeuds du troncon SAUF le tout premier —
    ce noeud est l'ouvrage source (reservoir ou station de pompage) lui-meme, pas un point de la
    conduite : sa "pression" ne depend que du niveau de l'ouvrage et de l'altitude du terrain a cet
    endroit, jamais du dimensionnement du troncon (revoir le decoupage du trace n'y changerait
    rien) — l'y appliquer produirait de fausses alertes. Le dernier noeud (le plus aval) doit EN
    PLUS respecter `downstream_residual_pressure` — on retient le plus exigeant des deux la ou ils
    se superposent."""
    required: dict[str, float] = {}
    if min_pressure is not None:
        for nid in node_ids_ordered[1:]:
            required[nid] = min_pressure
    end_node = node_ids_ordered[-1]
    end_required = min_pressure
    if downstream_residual_pressure is not None:
        end_required = max(end_required, downstream_residual_pressure) if end_required is not None else downstream_residual_pressure
    if end_required is not None:
        required[end_node] = end_required
    return required


def _check_terrain_pressure(
    node_ids_ordered: list[str],
    node_pk: Optional[dict[str, float]],
    node_cotes: dict[str, float],
    min_pressure: Optional[float],
    terrain_samples: Optional[list[tuple[float, float]]],
) -> list[str]:
    """Verifie la pression sur CHAQUE point echantillonne du profil de terrain (pas seulement aux
    noeuds reels, cf. docstring du module) une fois la ligne piezometrique finale connue. Une seule
    alerte agregee (jamais une par point — un terrain accidente en produirait des centaines) : PK de
    debut/fin de la zone en defaut et pire cas rencontre."""
    if min_pressure is None or not terrain_samples or not node_pk:
        return []
    violations: list[tuple[float, float, float]] = []
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
                violations.append((pk, z, pressure))
    if not violations:
        return []
    worst = min(violations, key=lambda v: v[2])
    pk_min = min(v[0] for v in violations)
    pk_max = max(v[0] for v in violations)
    return [
        f"Pression minimale non respectée sur le terrain entre PK {pk_min:.0f} m et PK {pk_max:.0f} m "
        f"({len(violations)} point(s) échantillonné(s), pire cas {worst[2]:.1f} m obtenus au PK "
        f"{worst[0]:.0f} m pour {min_pressure:.1f} m requis) — revoir le découpage du tracé "
        f"(brise-charge, tronçon plus court...)."
    ]


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
) -> tuple[dict[str, NodeCalcResult], list[SegmentCalcResult], list[str]]:
    """Une passe complete de la reconstruction AVAL -> AMONT + translation (cf. docstring module),
    parametree par un plancher de DN additionnel par segment (`min_dn_by_segment`) — permet a
    `solve_gravitaire_troncon` de ré-essayer avec un DN plus gros sur un segment precis quand la
    pression minimale n'est pas tenue (consigne utilisateur), sans dupliquer cette logique."""
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
            # segment — la classe de pression la moins chere disponible est retenue, et le calcul
            # s'applique meme si le PMS/la vitesse n'est pas respecte (alerte informative,
            # jamais bloquante contrairement au dimensionnement automatique).
            cand, pms_ok = _resolve_forced_pipe(catalog, seg.forced_material, seg.forced_dn, max_pms_needed)
            if cand is None:
                alerts.append(
                    f"{seg_label} : aucune conduite active {seg.forced_material} DN{seg.forced_dn} au "
                    f"catalogue — vérifier la fenêtre Conduites."
                )
                candidates = _candidates(catalog, 0.0, None, None, None) or list(catalog)
                cand = candidates[0]
            elif not pms_ok:
                alerts.append(
                    f"{seg_label} : le DN {seg.forced_dn} force en {seg.forced_material} ne respecte pas "
                    f"le PMS requis ({max_pms_needed:.1f} m, classe {cand.pressure_class} = {cand.pms_m:.1f} m) "
                    f"— calcul effectué malgré la contrainte matériau/DN forcée."
                )
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
        dn_floor = cand.dn

    # Cote "necessaire" reconstruite en tete vs. cote REELLEMENT disponible (le reservoir ne se
    # "dimensionne" pas comme une pompe) — translation de tout le profil si marge positive, alerte
    # sinon (cf. docstring module).
    start_node = node_ids_ordered[0]
    offset = effective_upstream_level_min - nodes[start_node].piezo_head
    if offset < -1e-6:
        alerts.append(
            f"Niveau du réservoir amont ({_node_label(start_node, node_pk)}, min = "
            f"{effective_upstream_level_min:.1f} m) insuffisant de {-offset:.1f} m pour garantir la "
            f"pression minimale sur l'ensemble du tronçon — revoir le découpage du tracé "
            f"(brise-charge, tronçon plus court...)."
        )

    for nid in node_ids_ordered:
        n = nodes[nid]
        nodes[nid] = replace(n, piezo_head=n.piezo_head + offset, pressure_dynamic=(n.pressure_dynamic or 0.0) + offset)

    for nid, required in required_by_node.items():
        actual = nodes[nid].pressure_dynamic or 0.0
        if actual < required - 1e-6:
            alerts.append(
                f"Pression insuffisante au {_node_label(nid, node_pk)} ({actual:.1f} m obtenus, "
                f"{required:.1f} m requis) — revoir le découpage du tracé (brise-charge, tronçon "
                f"plus court...)."
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
    required_by_node = _required_pressure_by_node(node_ids_ordered, min_pressure, downstream_residual_pressure)

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
            if seg.forced_dn is not None:
                # Materiau/DN force (consigne utilisateur) : jamais touche par l'augmentation
                # iterative, meme si le noeud aval viole la pression — l'alerte de pression
                # persiste (le segment force garde son DN quoi qu'il arrive).
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

    alerts = list(pass_alerts)
    alerts.extend(
        _check_terrain_pressure(
            node_ids_ordered, node_pk,
            {nid: nodes[nid].piezo_head for nid in node_ids_ordered},
            min_pressure, terrain_samples,
        )
    )

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
    alerts: list[str] = []

    dn_ceiling: Optional[int] = None
    prelim: list[tuple[SegmentSpec, CatalogPipe, float, float]] = []
    for i, seg in enumerate(segments_ordered):
        seg_label = (
            f"Segment entre {_node_label(node_ids_ordered[i], node_pk)} et "
            f"{_node_label(node_ids_ordered[i + 1], node_pk)}"
        )
        if seg.forced_material is not None and seg.forced_dn is not None:
            # Materiau/DN forces (consigne utilisateur) : le PMS requis n'est connu qu'une fois H0
            # determine plus bas (meme controle que le dimensionnement automatique, cf. boucle
            # `results` ci-dessous) — on retient ici la classe la moins chere, sans egard au PMS.
            cand, _pms_ok = _resolve_forced_pipe(catalog, seg.forced_material, seg.forced_dn, 0.0)
            if cand is None:
                alerts.append(
                    f"{seg_label} : aucune conduite active {seg.forced_material} DN{seg.forced_dn} "
                    f"au catalogue — vérifier la fenêtre Conduites."
                )
                candidates = _candidates(catalog, 0.0, None, None, None) or list(catalog)
                cand = candidates[0]
        else:
            min_di = min_di_mm_for_velocity(seg.flow_m3s, seg.max_velocity_ms)
            max_di = max_di_mm_for_velocity(seg.flow_m3s, seg.min_velocity_ms)
            candidates = _candidates(catalog, min_di, None, dn_ceiling, allowed_materials_fn, max_di_mm=max_di)
            if not candidates:
                alerts.append(
                    f"{seg_label} : aucune conduite active ne respecte vitesse/matériaux autorisés "
                    f"(DN plafonné à {dn_ceiling}) — vérifier le catalogue Conduites."
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
        dn_ceiling = cand.dn

    # Perte cumulee depuis le DEBUT du troncon (amont), noeud par noeud — la cote de depart H0
    # n'est pas encore fixee, seule cette perte l'est (elle ne depend que des DN choisis ci-dessus).
    cumulative_by_node: dict[str, float] = {node_ids_ordered[0]: 0.0}
    losses: list[float] = []
    running_loss = 0.0
    for i, (seg, cand, velocity, j) in enumerate(prelim):
        loss = j * seg.length_m * (1 + singular_loss_markup_pct / 100)
        losses.append(loss)
        running_loss += loss
        cumulative_by_node[node_ids_ordered[i + 1]] = running_loss

    required_by_node = _required_pressure_by_node(node_ids_ordered, min_pressure, downstream_residual_pressure)

    # H0 = plus petite cote de depart telle que, pour CHAQUE noeud exigeant une pression minimale,
    # H0 - perte_cumulee(noeud) - z(noeud) >= exigence(noeud) — forme close de "augmenter H0
    # jusqu'a ce que ca marche partout" (consigne utilisateur).
    h0 = 0.0
    for nid, required in required_by_node.items():
        h0 = max(h0, required + cumulative_by_node[nid] + node_ground_z[nid])

    # Meme principe pour CHAQUE point echantillonne du profil de terrain (pas seulement les noeuds
    # reels, cf. docstring du module) : la perte cumulee y est interpolee lineairement au sein du
    # segment qui le contient (J constant sur un segment a DN fixe, donc exact).
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
                cum_at_pk = cum_start + j * (pk - pk_start) * (1 + singular_loss_markup_pct / 100)
                h0 = max(h0, min_pressure + cum_at_pk + z)

    nodes: dict[str, NodeCalcResult] = {}
    for nid in node_ids_ordered:
        cote = h0 - cumulative_by_node[nid]
        nodes[nid] = NodeCalcResult(node_id=nid, piezo_head=cote, pressure_dynamic=cote - node_ground_z[nid])

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
