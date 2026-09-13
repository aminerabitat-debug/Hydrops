import pytest

from hydrops_api.services.crossings import OsmFeature, _feature_from_element, compute_crossings, trace_bbox


def test_compute_crossings_detects_perpendicular_road():
    # Trace horizontale de (2.0,48.0) a (2.01,48.0), route verticale qui la coupe en x=2.005.
    trace = [(2.0, 48.0), (2.005, 48.0), (2.01, 48.0)]
    crossing_road = OsmFeature(kind="highway", label="N7", coordinates=[(2.005, 47.99), (2.005, 48.01)])
    result = compute_crossings(trace, [crossing_road])
    assert len(result) == 1
    assert result[0].kind == "highway"
    assert result[0].label == "N7"
    assert result[0].pk >= 0.0


def test_compute_crossings_propagates_subtype_from_feature():
    # Consigne utilisateur : palette de couleurs par sous-categorie (classe de route/cours d'eau) —
    # le subtype de l'OsmFeature doit se retrouver tel quel sur le Crossing produit.
    trace = [(2.0, 48.0), (2.01, 48.0)]
    road = OsmFeature(kind="highway", label="N7", subtype="primary", coordinates=[(2.005, 47.99), (2.005, 48.01)])
    result = compute_crossings(trace, [road])
    assert result[0].subtype == "primary"
    assert result[0].source == "detected"


def test_feature_from_element_captures_subtype_even_when_named():
    # `label` privilegie le nom OSM quand il existe (name) — mais `subtype` doit rester la valeur
    # BRUTE du tag kind (ex. "primary"), independamment de la presence d'un nom, sinon la classe de
    # route/cours d'eau serait perdue pour toute voie nommee (consigne utilisateur).
    element = {
        "tags": {"highway": "primary", "name": "Route Nationale 7"},
        "geometry": [{"lon": 2.0, "lat": 48.0}, {"lon": 2.01, "lat": 48.0}],
    }
    feature = _feature_from_element(element)
    assert feature is not None
    assert feature.label == "Route Nationale 7"
    assert feature.subtype == "primary"


def test_feature_from_element_subtype_none_for_unnamed_zone():
    element = {
        "tags": {"landuse": "forest"},
        "geometry": [
            {"lon": 2.0, "lat": 48.0}, {"lon": 2.01, "lat": 48.0}, {"lon": 2.01, "lat": 48.01}, {"lon": 2.0, "lat": 48.0}
        ],
    }
    feature = _feature_from_element(element)
    assert feature is not None
    assert feature.kind == "forest"
    assert feature.subtype is None


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


def test_compute_crossings_detects_urban_zone_entry_and_exit():
    # Trace nord-sud de ~222 m (1 degre de latitude ~= 111320 m) ; zone urbaine rectangulaire
    # couvrant approximativement le tiers median (pk ~89-156 m) — avec un echantillonnage tous les
    # 20 m, l'entree/la sortie tombent sur les echantillons a pk=100 et pk=140.
    trace = [(2.0, 48.0), (2.0, 48.0020)]
    urban_zone = OsmFeature(
        kind="urban",
        label="residential",
        coordinates=[(1.999, 48.0008), (2.001, 48.0008), (2.001, 48.0014), (1.999, 48.0014), (1.999, 48.0008)],
    )
    result = compute_crossings(trace, [urban_zone])
    urban_crossings = [c for c in result if c.kind == "urban"]
    assert len(urban_crossings) == 2
    assert urban_crossings[0].label == "Entrée zone urbaine"
    assert urban_crossings[0].pk == pytest.approx(100.0, abs=1.0)
    assert urban_crossings[1].label == "Sortie zone urbaine"
    assert urban_crossings[1].pk == pytest.approx(140.0, abs=1.0)
    assert urban_crossings[0].pk < urban_crossings[1].pk


def test_compute_crossings_zone_still_inside_at_trace_end():
    # La zone (foret) couvre toute la fin de la trace : une "Entrée" doit etre rapportee (au premier
    # echantillon a l'interieur) mais aucune "Sortie" (jamais quittee avant la fin de la trace).
    trace = [(2.0, 48.0), (2.0, 48.0020)]
    forest_zone = OsmFeature(
        kind="forest",
        label="forest",
        coordinates=[(1.999, 48.0010), (2.001, 48.0010), (2.001, 48.01), (1.999, 48.01), (1.999, 48.0010)],
    )
    result = compute_crossings(trace, [forest_zone])
    forest_crossings = [c for c in result if c.kind == "forest"]
    assert len(forest_crossings) == 1
    assert forest_crossings[0].label == "Entrée zone forestière"


def test_compute_crossings_no_zone_features_gives_no_zone_crossings():
    trace = [(2.0, 48.0), (2.0, 48.0020)]
    assert compute_crossings(trace, []) == []
