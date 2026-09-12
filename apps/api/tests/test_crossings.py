from hydrops_api.services.crossings import OsmFeature, compute_crossings, trace_bbox


def test_compute_crossings_detects_perpendicular_road():
    # Trace horizontale de (2.0,48.0) a (2.01,48.0), route verticale qui la coupe en x=2.005.
    trace = [(2.0, 48.0), (2.005, 48.0), (2.01, 48.0)]
    crossing_road = OsmFeature(kind="highway", label="N7", coordinates=[(2.005, 47.99), (2.005, 48.01)])
    result = compute_crossings(trace, [crossing_road])
    assert len(result) == 1
    assert result[0].kind == "highway"
    assert result[0].label == "N7"
    assert result[0].pk >= 0.0


def test_compute_crossings_ignores_non_intersecting_feature():
    trace = [(2.0, 48.0), (2.01, 48.0)]
    far_road = OsmFeature(kind="highway", label="D1", coordinates=[(2.5, 47.99), (2.5, 48.01)])
    assert compute_crossings(trace, [far_road]) == []


def test_compute_crossings_differentiates_kinds():
    trace = [(2.0, 48.0), (2.02, 48.0)]
    features = [
        OsmFeature(kind="railway", label=None, coordinates=[(2.005, 47.99), (2.005, 48.01)]),
        OsmFeature(kind="waterway", label="Oued", coordinates=[(2.015, 47.99), (2.015, 48.01)]),
    ]
    result = compute_crossings(trace, features)
    kinds = {c.kind for c in result}
    assert kinds == {"railway", "waterway"}


def test_compute_crossings_sorted_by_pk():
    trace = [(2.0, 48.0), (2.02, 48.0)]
    features = [
        OsmFeature(kind="highway", label="far", coordinates=[(2.015, 47.99), (2.015, 48.01)]),
        OsmFeature(kind="highway", label="near", coordinates=[(2.005, 47.99), (2.005, 48.01)]),
    ]
    result = compute_crossings(trace, features)
    assert [c.label for c in result] == ["near", "far"]


def test_compute_crossings_ignores_parallel_overlap():
    # La "route" est confondue avec la trace sur un tronçon entier (chevauchement, pas une
    # traversee ponctuelle) — hors perimetre MVP, doit etre ignoree silencieusement.
    trace = [(2.0, 48.0), (2.02, 48.0)]
    overlapping = OsmFeature(kind="highway", label="parallel", coordinates=[(2.0, 48.0), (2.02, 48.0)])
    assert compute_crossings(trace, [overlapping]) == []


def test_trace_bbox_covers_all_points():
    coords = [(2.0, 48.0), (2.5, 48.3), (2.2, 47.8)]
    south, west, north, east = trace_bbox(coords)
    assert south == 47.8
    assert north == 48.3
    assert west == 2.0
    assert east == 2.5
