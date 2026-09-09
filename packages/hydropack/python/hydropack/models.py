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

from pydantic import BaseModel, Field, model_validator


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
        "pressure_break", "reservoir", "pumping_station", "intake", "treatment_plant",
        "tie_in", "terminal",
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
    data: Optional[dict] = None


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
    # shared/troncons.ts:tronconRegime cote frontend).
    upstream_water_level_max: Optional[float] = None
    upstream_water_level_min: Optional[float] = None
    min_pressure: Optional[float] = None
    downstream_residual_pressure: Optional[float] = None
    max_velocity: Optional[float] = None
