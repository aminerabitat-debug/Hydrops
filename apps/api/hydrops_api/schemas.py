"""DTO Pydantic pour les requetes API (Lot 1). Distincts des modeles hydropack : ce sont des
formulaires d'entree simplifies, pas le format de persistance — cf. docs/architecture/05-api.md."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AnnualVolumePointRequest(BaseModel):
    year: int
    value: float


class ProjectFormFields(BaseModel):
    """Champs communs a la creation et a l'edition (fenetre "Parametres du projet", meme
    formulaire dans les deux cas — cf. NewProjectDialog cote frontend)."""

    name: str
    client: Optional[str] = None
    currency: str = "EUR"
    default_water_type: str = "potable"
    study_horizon_years: int = 20
    project_lifetime_years: int = 30
    first_investment_year: int = 2026
    commissioning_year: int = 2028
    amortization_years: int = 25  # pilote le nombre de valeurs de la table de volume variable
    discount_rate: float = 0.06
    energy_price: float = 0.15
    annual_volume_value: float = 10.0  # Mm3/an — utilise si annual_volume_points absent (volume constant)
    # Volume variable : liste deja resolue (sans trous, une valeur par annee a partir de
    # commissioning_year) — l'interpolation/extrapolation des valeurs collees depuis le
    # presse-papier se fait cote client (NewProjectDialog), pas ici.
    annual_volume_points: Optional[list[AnnualVolumePointRequest]] = None
    lifetimes_pipes: int = 50
    lifetimes_civil_works: int = 50
    lifetimes_electromechanical: int = 15
    lifetimes_instrumentation_control: int = 10
    lifetimes_other: int = 20


class NewProjectRequest(ProjectFormFields):
    pass


class PatchProjectRequest(ProjectFormFields):
    """Remplacement complet des champs edites depuis "Parametres du projet" (meme formulaire que
    la creation, pre-rempli) — pas un patch partiel champ-par-champ."""


class NewVariantRequest(BaseModel):
    name: str = "Variante 1"
    description: Optional[str] = None


class PatchVariantRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PatchTraceRequest(BaseModel):
    hydraulic_direction: Optional[Literal["as_drawn", "reversed"]] = None


# Ajout/edition manuelle d'une traversee depuis la carte (consigne utilisateur) — `pk` suffit a la
# positionner, lon/lat sont recalcules serveur (projection sur la geometrie de la trace), jamais
# saisis par l'utilisateur.
class AddCrossingRequest(BaseModel):
    kind: Literal["highway", "railway", "waterway", "building", "urban", "forest"]
    pk: float = Field(ge=0)
    label: Optional[str] = None


class PatchCrossingRequest(BaseModel):
    kind: Optional[Literal["highway", "railway", "waterway", "building", "urban", "forest"]] = None
    pk: Optional[float] = Field(default=None, ge=0)
    label: Optional[str] = None


# Types de noeud creables depuis l'UI a ce stade (Lot 3 etape 1b) — high_point/low_point/
# sectioning_valve/control_valve/intake restent exclus (consigne utilisateur : pas de creation de
# points hauts/bas ni de vannes pour l'instant).
CreatableNodeType = Literal[
    "junction", "tie_in", "storage_reservoir", "surge_reservoir", "pumping_station", "pressure_break", "treatment_plant"
]


class NewNodeRequest(BaseModel):
    trace_id: str
    pk: float
    type: CreatableNodeType = "junction"
    name: Optional[str] = None
    data: Optional[dict] = None
    injected_flow: float = 0
    withdrawn_flow: float = 0


class PatchNodeRequest(BaseModel):
    """Retype/renomme un noeud existant — y compris une extremite structurelle de trace, qui peut
    porter un ouvrage (consigne utilisateur, Lot 3 etape 1c). Le type "terminal"/Extremite n'est
    plus autorise du tout (consigne utilisateur) : meme une extremite doit porter un type reel
    (junction au minimum) — cf. _is_structural_endpoint pour la protection contre la suppression,
    qui reste basee sur le PK, jamais sur le type. `data` remplace entierement la mise en donnees
    existante (meme convention que "Parametres du projet" : le formulaire soumet toujours l'etat
    complet, pas un patch champ-par-champ)."""

    type: Optional[CreatableNodeType] = None
    name: Optional[str] = None
    data: Optional[dict] = None
    injected_flow: Optional[float] = None
    withdrawn_flow: Optional[float] = None


class PatchSegmentRequest(BaseModel):
    material: Optional[str] = None
    dn: Optional[int] = None
    pressure_class: Optional[str] = None
    head_flow: Optional[float] = None
    upstream_water_level_max: Optional[float] = None
    upstream_water_level_min: Optional[float] = None
    # Non-null = la cote correspondante a ete saisie en relatif ("+N", cf. TronconDialog
    # resolveLevelInput) : valeur = N, mCE au-dessus du terrain du noeud de depart au moment de la
    # saisie. Permet de recalculer automatiquement la cote si ce noeud est deplace plus tard
    # (consigne utilisateur, cf. PATCH .../nodes/{id}/position) — une cote absolue (offset null)
    # n'est jamais recalculee automatiquement.
    upstream_water_level_max_offset: Optional[float] = None
    upstream_water_level_min_offset: Optional[float] = None
    min_pressure: Optional[float] = None
    downstream_residual_pressure: Optional[float] = None
    # Zone d'exclusion de la contrainte de pression min, en METRES, propre a ce tronçon (consigne
    # utilisateur) — remplace le pourcentage global de Preferences pour le CALCUL (cf.
    # run_calculation), qui ne sert plus que de base au prereplissage par defaut cote frontend.
    min_pressure_exclusion_m: Optional[float] = None
    max_velocity: Optional[float] = None
    min_velocity: Optional[float] = None
    # Contrainte Materiau/DN forcee (consigne utilisateur) — "" (chaine vide) sur forced_material
    # revient au dimensionnement automatique (meme convention que PatchNodeRequest.name), une
    # valeur non-vide exige forced_dn en meme temps (cf. patch_segment). Absent des deux = ne pas
    # toucher a la contrainte existante.
    forced_material: Optional[str] = None
    forced_dn: Optional[int] = None


class PatchNodePositionRequest(BaseModel):
    """Deplace un noeud existant le long de sa trace (consigne utilisateur : proposer de decaler
    le reservoir sur une alerte de terrain incompatible) — refuse sur une extremite structurelle
    ou un pk qui ne reste pas strictement entre ses voisins immediats, cf. patch_node_position."""

    pk: float


class PatchCatalogRowRequest(BaseModel):
    """Case "Actif" de la fenêtre Conduites (menu Base de données) — décocher exclut la ligne des
    recherches du moteur de calcul sans la supprimer (certains DN ne sont pas toujours standards
    selon les cas, consigne utilisateur)."""

    active: bool


class MaterialCriterionRuleRequest(BaseModel):
    dn_min: Optional[int] = None
    dn_max: Optional[int] = None
    fluid: Optional[str] = None
    materials: list[str] = []


class CalculationPreferencesRequest(BaseModel):
    """Fenêtre Préférences (menu Calcul, consigne utilisateur) : rugosité par matériau, hypothèses
    de calcul des pertes de charge — remplacement complet (même convention que "Paramètres du
    projet" : le formulaire soumet toujours l'état complet, pas un patch champ-par-champ)."""

    roughness_by_material: dict[str, float] = {}
    fluid_temperature_c: float = 20.0
    singular_loss_markup_pct: float = 10.0
    material_criteria: list[MaterialCriterionRuleRequest] = []
    default_min_pressure: Optional[float] = 5.0
    default_downstream_residual_pressure: Optional[float] = 10.0
    default_max_velocity: Optional[float] = 2.0
    default_min_velocity: Optional[float] = 0.2
    min_pressure_exclusion_pct: Optional[float] = 1.0
    hydraulic_segment_step_m: float = 200.0
