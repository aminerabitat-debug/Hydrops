"""(De)serialisation du conteneur .hydrops (ZIP) — docs/architecture/04-format-hydrops.md.

Lot 1 : metadata.json, project.json, techno_economic.json, traces/*.geometry.json + *.source.kml,
variants/*/variant.json. Lot 3 etape 1 ajoute variants/*/nodes.json + segments.json.
structures.json/results/ arrivent aux etapes suivantes du Lot 3 (les entites correspondantes
n'existent pas encore cote application).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from io import BytesIO

from .models import (
    CalculationPreferences,
    Metadata,
    Node,
    Project,
    Segment,
    TechnoEconomicAssumptions,
    TraceGeometry,
    Variant,
)
from .validation import validate


@dataclass
class TraceEntry:
    geometry: TraceGeometry
    source_kml_bytes: bytes = b""  # KML/KMZ d'origine, conserve tel quel (auditabilite, cf. V1-01)


@dataclass
class ProjectPackage:
    metadata: Metadata
    project: Project
    techno_economic: TechnoEconomicAssumptions = field(default_factory=TechnoEconomicAssumptions)
    calculation_preferences: CalculationPreferences = field(default_factory=CalculationPreferences)
    variants: dict[str, Variant] = field(default_factory=dict)
    traces: dict[str, TraceEntry] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    segments: dict[str, Segment] = field(default_factory=dict)


def _write_json(zf: zipfile.ZipFile, path: str, schema_name: str, payload: dict) -> None:
    validate(schema_name, payload)
    zf.writestr(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def _write_json_list(zf: zipfile.ZipFile, path: str, schema_name: str, items: list[dict]) -> None:
    for item in items:
        validate(schema_name, item)
    zf.writestr(path, json.dumps(items, indent=2, ensure_ascii=False, sort_keys=True))


def pack(pkg: ProjectPackage) -> bytes:
    """Serialise un ProjectPackage en octets .hydrops (ZIP), en validant chaque fichier interne
    contre son JSON Schema avant ecriture — un package invalide ne doit jamais etre produit."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_json(zf, "metadata.json", "metadata", pkg.metadata.model_dump(mode="json", exclude_none=True))
        _write_json(zf, "project.json", "project", pkg.project.model_dump(mode="json", exclude_none=True))
        _write_json(
            zf,
            "techno_economic.json",
            "techno_economic",
            pkg.techno_economic.model_dump(mode="json", exclude_none=True),
        )
        _write_json(
            zf,
            "calculation_preferences.json",
            "calculation_preferences",
            pkg.calculation_preferences.model_dump(mode="json", exclude_none=True),
        )

        for trace_id, entry in pkg.traces.items():
            _write_json(
                zf,
                f"traces/{trace_id}.geometry.json",
                "trace_geometry",
                entry.geometry.model_dump(mode="json", exclude_none=True),
            )
            if entry.source_kml_bytes:
                zf.writestr(f"traces/{trace_id}.source.kml", entry.source_kml_bytes)

        # Les traces sont partagees au niveau projet (pas de variant_id) — nodes.json/segments.json
        # restent groupes par variante via Node.variant_id (chaque variante a son propre reseau
        # sur les traces communes).
        node_variant_id = {nid: str(n.variant_id) for nid, n in pkg.nodes.items()}

        for variant_id, variant in pkg.variants.items():
            _write_json(
                zf,
                f"variants/{variant_id}/variant.json",
                "variant",
                variant.model_dump(mode="json", exclude_none=True),
            )

            variant_nodes = [
                n.model_dump(mode="json", exclude_none=True)
                for nid, n in pkg.nodes.items()
                if str(node_variant_id.get(nid)) == variant_id
            ]
            _write_json_list(zf, f"variants/{variant_id}/nodes.json", "node", variant_nodes)

            variant_segments = [
                s.model_dump(mode="json", exclude_none=True)
                for sid, s in pkg.segments.items()
                if str(node_variant_id.get(str(s.upstream_node_id))) == variant_id
            ]
            _write_json_list(zf, f"variants/{variant_id}/segments.json", "segment", variant_segments)

    return buffer.getvalue()


def unpack(data: bytes) -> ProjectPackage:
    """Deserialise des octets .hydrops en ProjectPackage, en validant chaque fichier interne
    contre son JSON Schema avant construction des modeles — un .hydrops corrompu ou non conforme
    est rejete explicitement (HydropackValidationError), jamais accepte avec des champs manquants
    traites silencieusement comme null (docs/architecture/09-strategie-tests.md §9.5)."""
    with zipfile.ZipFile(BytesIO(data), "r") as zf:
        names = set(zf.namelist())

        metadata_dict = json.loads(zf.read("metadata.json"))
        validate("metadata", metadata_dict)
        metadata = Metadata.model_validate(metadata_dict)

        project_dict = json.loads(zf.read("project.json"))
        validate("project", project_dict)
        project = Project.model_validate(project_dict)

        if "techno_economic.json" in names:
            techno_dict = json.loads(zf.read("techno_economic.json"))
            validate("techno_economic", techno_dict)
            techno_economic = TechnoEconomicAssumptions.model_validate(techno_dict)
        else:
            techno_economic = TechnoEconomicAssumptions()

        if "calculation_preferences.json" in names:
            prefs_dict = json.loads(zf.read("calculation_preferences.json"))
            validate("calculation_preferences", prefs_dict)
            calculation_preferences = CalculationPreferences.model_validate(prefs_dict)
        else:
            calculation_preferences = CalculationPreferences()

        traces: dict[str, TraceEntry] = {}
        for name in names:
            if name.startswith("traces/") and name.endswith(".geometry.json"):
                trace_id = name[len("traces/") : -len(".geometry.json")]
                geometry_dict = json.loads(zf.read(name))
                validate("trace_geometry", geometry_dict)
                geometry = TraceGeometry.model_validate(geometry_dict)
                kml_name = f"traces/{trace_id}.source.kml"
                source_kml_bytes = zf.read(kml_name) if kml_name in names else b""
                traces[trace_id] = TraceEntry(geometry=geometry, source_kml_bytes=source_kml_bytes)

        variants: dict[str, Variant] = {}
        nodes: dict[str, Node] = {}
        segments: dict[str, Segment] = {}
        for name in names:
            if name.startswith("variants/") and name.endswith("/variant.json"):
                variant_id = name[len("variants/") : -len("/variant.json")]
                variant_dict = json.loads(zf.read(name))
                validate("variant", variant_dict)
                variants[variant_id] = Variant.model_validate(variant_dict)

            elif name.startswith("variants/") and name.endswith("/nodes.json"):
                for node_dict in json.loads(zf.read(name)):
                    validate("node", node_dict)
                    node = Node.model_validate(node_dict)
                    nodes[str(node.id)] = node

            elif name.startswith("variants/") and name.endswith("/segments.json"):
                for segment_dict in json.loads(zf.read(name)):
                    validate("segment", segment_dict)
                    segment = Segment.model_validate(segment_dict)
                    segments[str(segment.id)] = segment

    return ProjectPackage(
        metadata=metadata,
        project=project,
        techno_economic=techno_economic,
        calculation_preferences=calculation_preferences,
        variants=variants,
        traces=traces,
        nodes=nodes,
        segments=segments,
    )
