"""hydropack: schema et (de)serialiseur du format de fichier .hydrops.

Voir docs/architecture/04-format-hydrops.md. Le JSON Schema (packages/hydropack/schema/*.json)
est la source unique de verite ; les modeles pydantic ci-dessous en sont une projection Python
ergonomique, revalidee contre le schema a chaque (de)serialisation (validation.py).
"""

from .models import Metadata, Project, TechnoEconomicAssumptions, TraceGeometry, Variant
from .serializer import ProjectPackage, pack, unpack

__all__ = [
    "Metadata",
    "Project",
    "TechnoEconomicAssumptions",
    "TraceGeometry",
    "Variant",
    "ProjectPackage",
    "pack",
    "unpack",
]
