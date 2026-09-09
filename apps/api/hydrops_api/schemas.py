"""DTO Pydantic pour les requetes API (Lot 1). Distincts des modeles hydropack : ce sont des
formulaires d'entree simplifies, pas le format de persistance — cf. docs/architecture/05-api.md."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


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


# Types de noeud creables depuis l'UI a ce stade (Lot 3 etape 1b) — high_point/low_point/
# sectioning_valve/control_valve/intake restent exclus (consigne utilisateur : pas de creation de
# points hauts/bas ni de vannes pour l'instant).
CreatableNodeType = Literal["junction", "tie_in", "reservoir", "pumping_station", "pressure_break", "treatment_plant"]


class NewNodeRequest(BaseModel):
    trace_id: str
    pk: float
    type: CreatableNodeType = "junction"
    name: Optional[str] = None


class PatchNodeRequest(BaseModel):
    """Retype/renomme un noeud existant — y compris une extremite structurelle de trace, qui peut
    porter un ouvrage (consigne utilisateur, Lot 3 etape 1c). Le type "terminal"/Extremite n'est
    plus autorise du tout (consigne utilisateur) : meme une extremite doit porter un type reel
    (junction au minimum) — cf. _is_structural_endpoint pour la protection contre la suppression,
    qui reste basee sur le PK, jamais sur le type."""

    type: Optional[CreatableNodeType] = None
    name: Optional[str] = None


class PatchSegmentRequest(BaseModel):
    material: Optional[str] = None
    dn: Optional[int] = None
    pressure_class: Optional[str] = None
