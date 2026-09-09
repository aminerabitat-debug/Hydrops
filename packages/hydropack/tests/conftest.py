import uuid
from datetime import datetime, timezone

import pytest

from hydropack.models import (
    AnnualVolumeConstant,
    LifetimesByCategory,
    LineStringGeometry,
    Metadata,
    Project,
    TechnoEconomicAssumptions,
    TraceGeometry,
    Variant,
)


@pytest.fixture
def sample_project() -> Project:
    return Project(
        id=uuid.uuid4(),
        name="Adduction Test",
        client="Client Test",
        currency="EUR",
        default_water_type="potable",
        study_horizon_years=20,
        project_lifetime_years=30,
        first_investment_year=2026,
        commissioning_year=2028,
        amortization_years=25,
        discount_rate=0.06,
        energy_price=0.15,
        annual_volume=AnnualVolumeConstant(mode="constant", value=1000.0),
        lifetimes_by_category=LifetimesByCategory(
            pipes=50, civil_works=50, electromechanical=15, instrumentation_control=10, other=20
        ),
    )


@pytest.fixture
def sample_metadata() -> Metadata:
    now = datetime.now(timezone.utc)
    return Metadata(software_version="0.1.0", created_at=now, modified_at=now)


@pytest.fixture
def sample_trace(sample_project) -> TraceGeometry:
    return TraceGeometry(
        id=uuid.uuid4(),
        project_id=sample_project.id,
        source="kml_import",
        geometry=LineStringGeometry(
            type="LineString",
            coordinates=[[2.35, 48.85], [2.36, 48.86], [2.37, 48.87]],
        ),
        length=1500.0,
        water_type="potable",
    )


@pytest.fixture
def sample_techno_economic() -> TechnoEconomicAssumptions:
    return TechnoEconomicAssumptions()
