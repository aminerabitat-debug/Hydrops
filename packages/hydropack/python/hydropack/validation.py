"""Validation des fichiers internes .hydrops contre le JSON Schema (source unique de verite).

docs/architecture/04-format-hydrops.md : "chaque fichier interne au .hydrops est valide contre
son JSON Schema" — cette validation s'applique en plus du typage pydantic, qui ne garantit pas
a lui seul l'egalite avec le schema publie (divergence possible si l'un est modifie sans l'autre).
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"

_SCHEMA_FILES = {
    "metadata": "metadata.schema.json",
    "project": "project.schema.json",
    "techno_economic": "techno_economic.schema.json",
    "trace_geometry": "trace_geometry.schema.json",
    "variant": "variant.schema.json",
    "node": "node.schema.json",
    "segment": "segment.schema.json",
    "structure": "structure.schema.json",
    "calculation": "calculation.schema.json",
    "results": "results.schema.json",
}


class HydropackValidationError(ValueError):
    def __init__(self, schema_name: str, errors: list[str]):
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(f"Validation '{schema_name}' echouee: {'; '.join(errors)}")


@functools.lru_cache(maxsize=None)
def _load_schema(schema_name: str) -> dict:
    path = SCHEMA_DIR / _SCHEMA_FILES[schema_name]
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate(schema_name: str, instance: dict[str, Any]) -> None:
    """Leve HydropackValidationError si `instance` ne respecte pas le schema `schema_name`."""
    schema = _load_schema(schema_name)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        messages = [f"{'/'.join(str(p) for p in e.path) or '<racine>'}: {e.message}" for e in errors]
        raise HydropackValidationError(schema_name, messages)
