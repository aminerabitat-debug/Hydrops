import uuid

import pytest

from hydropack.models import Node, Segment, Variant
from hydropack.serializer import ProjectPackage, TraceEntry, pack, unpack
from hydropack.validation import HydropackValidationError, validate


def _build_package(sample_metadata, sample_project, sample_techno_economic, sample_trace, nodes=None, segments=None):
    variant = Variant(id=uuid.uuid4(), project_id=sample_project.id, name="Variante 1")
    return ProjectPackage(
        metadata=sample_metadata,
        project=sample_project,
        techno_economic=sample_techno_economic,
        variants={str(variant.id): variant},
        traces={str(sample_trace.id): TraceEntry(geometry=sample_trace, source_kml_bytes=b"<kml>fixture</kml>")},
        nodes={str(n.id): n for n in (nodes or [])},
        segments={str(s.id): s for s in (segments or [])},
    ), variant


def _build_sample_nodes_and_segments(trace_geometry, variant_id):
    upstream = Node(
        id=uuid.uuid4(),
        trace_id=trace_geometry.id,
        variant_id=variant_id,
        type="terminal",
        pk=0.0,
        x=2.35,
        y=48.85,
        z=50.0,
        z_source="dem",
    )
    downstream = Node(
        id=uuid.uuid4(),
        trace_id=trace_geometry.id,
        variant_id=variant_id,
        type="terminal",
        pk=trace_geometry.length,
        x=2.37,
        y=48.87,
        z=55.0,
        z_source="dem",
    )
    segment = Segment(
        id=uuid.uuid4(),
        upstream_node_id=upstream.id,
        downstream_node_id=downstream.id,
        pk_start=0.0,
        pk_end=trace_geometry.length,
        length=trace_geometry.length,
        material="pehd_pe100",
        dn=160,
        di=130.9,
        de=160.0,
        pressure_class="pn10",
        roughness=1e-5,
        flow=0.0,
        forced=False,
    )
    return [upstream, downstream], [segment]


def test_roundtrip_preserves_project(sample_metadata, sample_project, sample_techno_economic, sample_trace):
    pkg, _ = _build_package(sample_metadata, sample_project, sample_techno_economic, sample_trace)
    data = pack(pkg)
    restored = unpack(data)
    assert restored.project.id == pkg.project.id
    assert restored.project.name == pkg.project.name
    assert restored.project.discount_rate == pkg.project.discount_rate
    assert restored.project.commissioning_year == pkg.project.commissioning_year


def test_roundtrip_preserves_trace_geometry_and_source_kml(
    sample_metadata, sample_project, sample_techno_economic, sample_trace
):
    pkg, _ = _build_package(sample_metadata, sample_project, sample_techno_economic, sample_trace)
    data = pack(pkg)
    restored = unpack(data)

    trace_id = str(sample_trace.id)
    restored_entry = restored.traces[trace_id]
    assert restored_entry.geometry.geometry.coordinates == sample_trace.geometry.coordinates
    assert restored_entry.geometry.project_id == sample_project.id
    assert restored_entry.source_kml_bytes == b"<kml>fixture</kml>"


def test_roundtrip_preserves_variant(sample_metadata, sample_project, sample_techno_economic, sample_trace):
    pkg, variant = _build_package(sample_metadata, sample_project, sample_techno_economic, sample_trace)
    data = pack(pkg)
    restored = unpack(data)

    assert restored.variants[str(variant.id)].name == "Variante 1"


def test_roundtrip_preserves_nodes_and_segments(
    sample_metadata, sample_project, sample_techno_economic, sample_trace
):
    variant_id = uuid.uuid4()
    nodes, segments = _build_sample_nodes_and_segments(sample_trace, variant_id)
    pkg, variant = _build_package(sample_metadata, sample_project, sample_techno_economic, sample_trace, nodes, segments)
    # Reconstruit le package avec la meme variante que celle utilisee pour les noeuds, pour que
    # pack() les regroupe correctement sous variants/{variant.id}/.
    pkg.variants = {str(variant_id): Variant(id=variant_id, project_id=sample_project.id, name="Variante 1")}
    data = pack(pkg)
    restored = unpack(data)

    assert {str(n.id) for n in nodes} == set(restored.nodes.keys())
    assert restored.nodes[str(nodes[0].id)].type == "terminal"
    assert restored.nodes[str(nodes[1].id)].pk == sample_trace.length

    assert {str(s.id) for s in segments} == set(restored.segments.keys())
    restored_segment = restored.segments[str(segments[0].id)]
    assert restored_segment.upstream_node_id == nodes[0].id
    assert restored_segment.downstream_node_id == nodes[1].id
    assert restored_segment.dn == 160


def test_pack_is_a_valid_zip_with_expected_layout(
    sample_metadata, sample_project, sample_techno_economic, sample_trace
):
    import zipfile
    from io import BytesIO

    variant_id = uuid.uuid4()
    nodes, segments = _build_sample_nodes_and_segments(sample_trace, variant_id)
    pkg, _ = _build_package(sample_metadata, sample_project, sample_techno_economic, sample_trace, nodes, segments)
    pkg.variants = {str(variant_id): Variant(id=variant_id, project_id=sample_project.id, name="Variante 1")}
    data = pack(pkg)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = set(zf.namelist())
    assert "metadata.json" in names
    assert "project.json" in names
    assert "techno_economic.json" in names
    assert any(n.endswith(".geometry.json") for n in names)
    assert any(n.endswith(".source.kml") for n in names)
    assert any(n.endswith("/variant.json") for n in names)
    assert any(n.endswith("/nodes.json") for n in names)
    assert any(n.endswith("/segments.json") for n in names)


def test_unpack_rejects_schema_violation(sample_metadata, sample_project, sample_techno_economic, sample_trace):
    import zipfile
    from io import BytesIO

    pkg, _ = _build_package(sample_metadata, sample_project, sample_techno_economic, sample_trace)
    data = pack(pkg)

    # Corrompt project.json : retire un champ requis par le schema (discount_rate)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        contents = {n: zf.read(n) for n in zf.namelist()}
    import json

    project_dict = json.loads(contents["project.json"])
    del project_dict["discount_rate"]
    contents["project.json"] = json.dumps(project_dict).encode("utf-8")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in contents.items():
            zf.writestr(name, content)

    with pytest.raises(HydropackValidationError):
        unpack(buffer.getvalue())


def test_validate_helper_rejects_wrong_type():
    with pytest.raises(HydropackValidationError):
        validate("metadata", {"format_version": 1.0})
