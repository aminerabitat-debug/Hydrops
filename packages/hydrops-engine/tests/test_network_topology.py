from hydrops_engine.topology import (
    group_into_troncons,
    order_nodes_by_pk,
    validate_non_increasing_di,
    validate_pk_strictly_increasing,
)


def test_order_nodes_by_pk_sorts_ascending():
    nodes = [("b", 50.0), ("a", 0.0), ("c", 100.0)]
    ordered = order_nodes_by_pk(nodes)
    assert [n[0] for n in ordered] == ["a", "b", "c"]


def test_order_nodes_by_pk_does_not_mutate_input():
    nodes = [("b", 50.0), ("a", 0.0)]
    order_nodes_by_pk(nodes)
    assert nodes == [("b", 50.0), ("a", 0.0)]


def test_validate_pk_strictly_increasing_accepts_valid_sequence():
    ordered = [("a", 0.0), ("b", 50.0), ("c", 100.0)]
    assert validate_pk_strictly_increasing(ordered) == []


def test_validate_pk_strictly_increasing_flags_duplicate_pk():
    ordered = [("a", 0.0), ("b", 50.0), ("c", 50.0)]
    violations = validate_pk_strictly_increasing(ordered)
    assert len(violations) == 1
    assert violations[0].code == "DUPLICATE_OR_DECREASING_PK"
    assert violations[0].node_id == "c"


def test_validate_non_increasing_di_accepts_non_increasing_sequence():
    segments = [("s1", 200.0), ("s2", 150.0), ("s3", 150.0), ("s4", 100.0)]
    assert validate_non_increasing_di(segments) == []


def test_validate_non_increasing_di_flags_increase_downstream():
    segments = [("s1", 100.0), ("s2", 150.0)]
    violations = validate_non_increasing_di(segments)
    assert len(violations) == 1
    assert violations[0].code == "DI_INCREASES_DOWNSTREAM"
    assert violations[0].segment_id == "s2"


def test_validate_non_increasing_di_flags_only_the_increasing_pair():
    segments = [("s1", 200.0), ("s2", 100.0), ("s3", 150.0)]
    violations = validate_non_increasing_di(segments)
    assert len(violations) == 1
    assert violations[0].segment_id == "s3"


def test_group_into_troncons_single_segment_between_terminals():
    nodes = [("a", "terminal", 0.0), ("b", "terminal", 100.0)]
    edges = {("a", "b"): "s1"}
    groups = group_into_troncons(nodes, edges)
    assert len(groups) == 1
    assert groups[0].start_node_id == "a"
    assert groups[0].end_node_id == "b"
    assert groups[0].segment_ids == ("s1",)
    assert groups[0].pk_start == 0.0
    assert groups[0].pk_end == 100.0


def test_group_into_troncons_junction_and_piquage_are_transparent():
    # a(terminal) -- s1 -- j(junction, DN change) -- s2 -- p(tie_in) -- s3 -- b(terminal)
    # doit produire UN SEUL troncon a=>b regroupant s1,s2,s3 (decision utilisateur).
    nodes = [
        ("a", "terminal", 0.0),
        ("j", "junction", 50.0),
        ("p", "tie_in", 80.0),
        ("b", "terminal", 120.0),
    ]
    edges = {("a", "j"): "s1", ("j", "p"): "s2", ("p", "b"): "s3"}
    groups = group_into_troncons(nodes, edges)
    assert len(groups) == 1
    assert groups[0].start_node_id == "a"
    assert groups[0].end_node_id == "b"
    assert groups[0].segment_ids == ("s1", "s2", "s3")


def test_group_into_troncons_splits_at_real_ouvrages():
    # a(terminal) -- s1 -- r(storage_reservoir) -- s2 -- sp(pumping_station) -- s3 -- b(terminal)
    nodes = [
        ("a", "terminal", 0.0),
        ("r", "storage_reservoir", 40.0),
        ("sp", "pumping_station", 90.0),
        ("b", "terminal", 150.0),
    ]
    edges = {("a", "r"): "s1", ("r", "sp"): "s2", ("sp", "b"): "s3"}
    groups = group_into_troncons(nodes, edges)
    assert [(g.start_node_id, g.end_node_id, g.segment_ids) for g in groups] == [
        ("a", "r", ("s1",)),
        ("r", "sp", ("s2",)),
        ("sp", "b", ("s3",)),
    ]


def test_group_into_troncons_empty_for_single_node():
    assert group_into_troncons([("a", "terminal", 0.0)], {}) == []
