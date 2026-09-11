"""Modeles pydantic miroir des JSON Schema de packages/hydropack/schema/.

Lot 3 etape 1 (noeuds/segments) ajoute Node et Segment. Structure/Calculation/Results n'existent
toujours pas comme entites manipulees par l'application (etapes suivantes du Lot 3, voir
docs/functional-spec §21). Les schemas JSON correspondants existent deja (Phase 0) comme contrat
cible.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class Metadata(BaseModel):
    format_version: str = "1.0.0"
    software_version: str
    created_at: datetime
    modified_at: datetime
    units_system: Literal["SI", "US"] = "SI"
    generator: str = "HydroPS Web"


class AnnualVolumeConstant(BaseModel):
    mode: Literal["constant"]
    value: float = Field(ge=0)


class AnnualVolumePoint(BaseModel):
    year: int
    value: float = Field(ge=0)


class AnnualVolumeTable(BaseModel):
    mode: Literal["table"]
    points: list[AnnualVolumePoint] = Field(min_length=1)


class LifetimesByCategory(BaseModel):
    pipes: int = Field(ge=1)
    civil_works: int = Field(ge=1)
    electromechanical: int = Field(ge=1)
    instrumentation_control: int = Field(ge=1)
    other: int = Field(ge=1)


class ProjectOptions(BaseModel):
    include_reinvestment: bool = False
    include_residual_value: bool = False


class Branding(BaseModel):
    logo_asset_ref: Optional[str] = None
    doc_number: Optional[str] = None
    revision: Optional[str] = None
    issue_date: Optional[date] = None
    prepared_by: Optional[str] = None
    checked_by: Optional[str] = None
    approved_by: Optional[str] = None


class Project(BaseModel):
    id: UUID
    name: str = Field(min_length=1)
    client: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    default_water_type: str
    study_horizon_years: int = Field(ge=1)
    project_lifetime_years: int = Field(ge=1)
    first_investment_year: int
    commissioning_year: int
    amortization_years: int = Field(ge=1)
    discount_rate: float = Field(ge=0, le=1)
    energy_price: float = Field(ge=0)
    annual_volume: AnnualVolumeConstant | AnnualVolumeTable  # Mm3/an
    lifetimes_by_category: LifetimesByCategory
    options: ProjectOptions = Field(default_factory=ProjectOptions)
    language: Literal["fr", "en"] = "fr"
    units_system: Literal["SI", "US"] = "SI"
    number_format: Optional[str] = None
    page_format: Literal["A4", "Letter"] = "A4"
    branding: Optional[Branding] = None


class MaintenanceRule(BaseModel):
    asset_category: str
    mode: Literal["percent_of_capex", "table"]
    percent_value: Optional[float] = Field(default=None, ge=0, le=1)
    table: Optional[list[dict]] = None


class OverheadRule(BaseModel):
    mode: Literal["fixed_value", "percent_of_opex"]
    value: float = Field(ge=0)


class AncillaryCost(BaseModel):
    label: str
    amount: float
    year: Optional[int] = None


class TechnoEconomicAssumptions(BaseModel):
    maintenance_rules: list[MaintenanceRule] = Field(default_factory=list)
    overhead_rule: Optional[OverheadRule] = None
    ancillary_costs: list[AncillaryCost] = Field(default_factory=list)
    catalog_version: Optional[str] = None


class LineStringGeometry(BaseModel):
    type: Literal["LineString"]
    coordinates: list[list[float]] = Field(min_length=2)


class ProfilePoint(BaseModel):
    pk: float
    z: float


class ElevationProfile(BaseModel):
    dem_source: Optional[str] = None
    dem_version: Optional[str] = None
    raw: list[ProfilePoint] = Field(default_factory=list)
    smoothed: list[ProfilePoint] = Field(default_factory=list)
    candidate_high_points: list[ProfilePoint] = Field(default_factory=list)
    candidate_low_points: list[ProfilePoint] = Field(default_factory=list)


class TraceGeometry(BaseModel):
    id: UUID
    project_id: UUID
    source: Literal["kml_import", "kmz_import"]
    source_file_ref: Optional[str] = None
    geometry: LineStringGeometry
    length: float = Field(ge=0)
    pk_origin: float = 0.0
    hydraulic_direction: Literal["as_drawn", "reversed"] = "as_drawn"
    topological_order: int = Field(ge=0, default=0)
    water_type: str
    parent_trace_id: Optional[UUID] = None
    parent_node_id: Optional[UUID] = None
    elevation_profile: Optional[ElevationProfile] = None


class Variant(BaseModel):
    id: UUID
    project_id: UUID
    name: str = Field(min_length=1)
    description: Optional[str] = None
    duplicated_from_variant_id: Optional[UUID] = None
    forcings: list[dict] = Field(default_factory=list)
    optimization_mode: Literal["auto", "manual"] = "auto"
    status: Literal["draft", "calculated", "stale"] = "draft"

    @model_validator(mode="after")
    def _duplicate_not_self(self) -> "Variant":
        if self.duplicated_from_variant_id == self.id:
            raise ValueError("Une variante ne peut pas etre dupliquee depuis elle-meme")
        return self


class NodeParentLink(BaseModel):
    trace_id: UUID
    node_id: UUID


class Node(BaseModel):
    id: UUID
    trace_id: UUID
    variant_id: UUID
    type: Literal[
        "junction", "high_point", "low_point", "sectioning_valve", "control_valve",
        "pressure_break", "storage_reservoir", "surge_reservoir", "pumping_station", "intake",
        "treatment_plant", "tie_in", "terminal",
    ]
    name: Optional[str] = None
    pk: float
    x: float
    y: float
    z: float
    z_source: Literal["dem", "manual", "surveyed"]
    injected_flow: float = 0
    withdrawn_flow: float = 0
    parent_link: Optional[NodeParentLink] = None
    validated: bool = True
    structure_id: Optional[UUID] = None
    # Mise en donnees detaillee specifique au type d'ouvrage (cdc §8) — champs libres varient selon
    # le type (station de pompage, reservoir, brise charge, station de traitement...), definis cote
    # frontend (shared/ouvrageFields.ts) ; le backend les stocke tels quels sans validation par champ.
    # Pour un Piquage (tie_in), `data` ne porte qu'un seul champ optionnel,
    # `include_withdrawal_in_sizing` (bool) : coche par defaut, decoche = le debit preleve par ce
    # piquage n'est PAS soustrait du debit de dimensionnement des troncons aval (consigne
    # utilisateur : "des fois on veut dimensionner...pour ce debit [de tete], d'autres fois on veut
    # optimiser et soustraire le debit de prelevement en route").
    data: Optional[dict] = None
    # Sorties du calcul hydraulique (bouton Calculer), par piquet — cf.
    # packages/hydrops-engine/hydrops_engine/hydraulics.py. None tant qu'aucun calcul n'a ete lance
    # ou que le noeud n'appartient pas a un troncon calculable.
    piezo_head: Optional[float] = None
    pressure_dynamic: Optional[float] = None
    pressure_static_max: Optional[float] = None
    pressure_static_min: Optional[float] = None

    @field_validator("type", mode="before")
    @classmethod
    def _map_legacy_reservoir_type(cls, value: object) -> object:
        """Alias de lecture (consigne utilisateur) : l'ancien type "reservoir" (avant la scission
        Reservoir de stockage / Reservoir de mise en charge) reste lisible sur un .hydrops deja
        exporte — mappe vers "storage_reservoir", jamais propose en creation (CreatableNodeType,
        cote API, ne connait plus "reservoir")."""
        return "storage_reservoir" if value == "reservoir" else value


class Segment(BaseModel):
    id: UUID
    upstream_node_id: UUID
    downstream_node_id: UUID
    pk_start: float
    pk_end: float
    length: float = Field(ge=0)
    material: str
    dn: int
    di: float = Field(ge=0)
    de: Optional[float] = Field(default=None, ge=0)
    pressure_class: str
    roughness: float = Field(ge=0)
    flow: float = 0
    forced: bool = False
    # Parametres hydrauliques du troncon (cdc §8), saisis depuis la fenetre "Modifier le troncon" —
    # le sous-ensemble pertinent depend du regime (gravitaire vs refoulement, cf.
    # shared/troncons.ts:tronconRegime cote frontend). `head_flow` (debit de tete, m3/h) est
    # renseigne au niveau du troncon quel que soit son regime (consigne utilisateur : pas de champ
    # Debit sur la station de pompage, un troncon peut demarrer sur n'importe quel ouvrage).
    head_flow: Optional[float] = None
    upstream_water_level_max: Optional[float] = None
    upstream_water_level_min: Optional[float] = None
    # Non-null = la cote correspondante a ete saisie en relatif ("+N" cote frontend) : valeur = N,
    # permet de la recalculer automatiquement si le noeud de depart du tronçon est deplace
    # (consigne utilisateur — cf. routers/network.py:patch_node_position). None = cote absolue,
    # jamais recalculee automatiquement.
    upstream_water_level_max_offset: Optional[float] = None
    upstream_water_level_min_offset: Optional[float] = None
    min_pressure: Optional[float] = None
    downstream_residual_pressure: Optional[float] = None
    max_velocity: Optional[float] = None
    # Preferences, consigne utilisateur (defaut 0.2 m/s) : plancher de vitesse — l'augmentation
    # iterative du DN gravitaire pour resoudre un defaut de pression (cf.
    # hydrops_engine.hydraulics.solve_gravitaire_troncon) ne descend jamais sous cette vitesse.
    min_velocity: Optional[float] = None
    # Sorties du calcul hydraulique (bouton Calculer) pour ce segment — cf.
    # packages/hydrops-engine/hydrops_engine/hydraulics.py. `flow`/`roughness` (deja existants
    # ci-dessus) sont aussi ecrases par le calcul : `flow` devient le debit reellement transite
    # (apres soustraction eventuelle des piquages amont), `roughness` la valeur de Preferences pour
    # le materiau retenu. None tant qu'aucun calcul n'a ete lance.
    velocity: Optional[float] = None
    head_loss_unit: Optional[float] = None  # J, pertes de charge lineaires unitaires (m/m)
    head_loss_segment: Optional[float] = None  # J * longueur * (1 + majoration singulieres) (m)
    head_loss_cumulative: Optional[float] = None  # cumul depuis le debut du troncon calcule (m)


class MaterialCriterionRule(BaseModel):
    """Une ligne du tableau "Critères de choix des matériaux des conduites" (menu Calcul >
    Preferences, consigne utilisateur) : materiaux autorises pour une plage de DN et,
    eventuellement, un type de fluide precis (None = s'applique a tous les fluides)."""

    dn_min: Optional[int] = None
    dn_max: Optional[int] = None
    fluid: Optional[str] = None
    materials: list[str] = Field(default_factory=list)


class CalculationPreferences(BaseModel):
    """Hypotheses de calcul hydraulique (menu Calcul > Preferences, consigne utilisateur) —
    document auxiliaire au niveau du projet (comme TechnoEconomicAssumptions), partage par toutes
    les variantes. Un point de depart editable (cdc §15), pas une verite figee."""

    roughness_by_material: dict[str, float] = Field(default_factory=dict)
    fluid_temperature_c: float = 20.0
    singular_loss_markup_pct: float = 10.0
    material_criteria: list[MaterialCriterionRule] = Field(default_factory=list)
    # Valeurs par defaut proposees a l'ouverture de "Modifier le tronçon" quand le tronçon n'a pas
    # encore sa propre valeur (consigne utilisateur) — n'influencent jamais un calcul directement,
    # seulement le prereplissage cote frontend. Valeurs de depart usuelles (consigne utilisateur),
    # modifiables dans la fenetre Preferences — pas une verite figee.
    default_min_pressure: Optional[float] = 5.0
    default_downstream_residual_pressure: Optional[float] = 10.0
    default_max_velocity: Optional[float] = 2.0
    default_min_velocity: Optional[float] = 0.2
