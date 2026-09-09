def _default_variant_id(project_state) -> str:
    return project_state["variants"][0]["id"]


def _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id = _default_variant_id(project_state)
    trace = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    return variant_id, trace


def test_import_seeds_two_terminal_nodes_and_one_segment(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)

    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    assert len(nodes) == 2
    assert {n["type"] for n in nodes} == {"junction"}
    assert nodes[0]["pk"] == 0.0
    assert nodes[1]["pk"] == trace["length"]

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    assert len(segments) == 1
    assert segments[0]["upstream_node_id"] == nodes[0]["id"]
    assert segments[0]["downstream_node_id"] == nodes[1]["id"]
    assert segments[0]["forced"] is False


def test_add_junction_node_splits_segment_in_two(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    trace_id = trace["id"]
    mid_pk = trace["length"] / 2

    response = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace_id, "pk": mid_pk},
    )
    assert response.status_code == 201, response.text
    junction = response.json()
    assert junction["type"] == "junction"
    assert abs(junction["pk"] - mid_pk) < 1e-6

    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    assert len(nodes) == 3

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    assert len(segments) == 2
    assert {s["upstream_node_id"] for s in segments} | {s["downstream_node_id"] for s in segments} == {
        n["id"] for n in nodes
    }


def test_add_junction_node_rejects_pk_out_of_bounds(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    response = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": trace["length"] + 100},
    )
    assert response.status_code == 422


def test_delete_junction_node_merges_segments_back(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    mid_pk = trace["length"] / 2
    junction = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": mid_pk},
    ).json()

    response = client.delete(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{junction['id']}")
    assert response.status_code == 204

    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    assert len(nodes) == 2
    assert len(segments) == 1
    assert segments[0]["length"] == trace["length"]


def test_delete_terminal_node_is_rejected(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    response = client.delete(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{nodes[0]['id']}")
    assert response.status_code == 400


def test_patch_segment_applies_catalog_and_marks_forced(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"material": "fonte_ductile", "dn": 200, "pressure_class": "k9"},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["material"] == "fonte_ductile"
    assert updated["dn"] == 200
    assert updated["forced"] is True
    assert updated["di"] == 209.4


def test_patch_segment_applies_hydraulic_fields_and_marks_forced_even_unchanged(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    """"force" reflete desormais "les donnees ont ete validees via la fenetre Modifier" — pas
    seulement un ecart par rapport aux valeurs catalogue par defaut (consigne utilisateur)."""
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    default = segments[0]

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "material": default["material"],
            "dn": default["dn"],
            "pressure_class": default["pressure_class"],
            "upstream_water_level_max": 120.5,
            "upstream_water_level_min": 118.0,
            "min_pressure": 15.0,
            "downstream_residual_pressure": 20.0,
            "max_velocity": 1.5,
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["forced"] is True
    assert updated["upstream_water_level_max"] == 120.5
    assert updated["upstream_water_level_min"] == 118.0
    assert updated["min_pressure"] == 15.0
    assert updated["downstream_residual_pressure"] == 20.0
    assert updated["max_velocity"] == 1.5


def test_reset_segment_also_clears_hydraulic_fields(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"material": "fonte_ductile", "dn": 200, "pressure_class": "k9", "max_velocity": 1.5},
    )
    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}/reset")
    assert response.status_code == 200, response.text
    reset = response.json()
    assert reset["forced"] is False
    assert "max_velocity" not in reset


def test_patch_node_sets_ouvrage_data_and_flows(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    node_id = nodes[0]["id"]

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{node_id}",
        json={
            "type": "tie_in",
            "name": "P1",
            "withdrawn_flow": 12.5,
            "data": {"note": "test"},
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["withdrawn_flow"] == 12.5
    assert updated["data"] == {"note": "test"}


def test_add_node_with_data_and_flows(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    response = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={
            "trace_id": trace["id"],
            "pk": 20,
            "type": "pumping_station",
            "name": "SP1",
            "data": {"installation_type": "Submersible"},
        },
    )
    assert response.status_code == 201, response.text
    node = response.json()
    assert node["data"] == {"installation_type": "Submersible"}


def test_patch_segment_rejects_unknown_catalog_combination(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"dn": 9999},
    )
    assert response.status_code == 422


def test_reset_segment_reverts_to_catalog_default_and_clears_forced(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    default = segments[0]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"material": "fonte_ductile", "dn": 200, "pressure_class": "k9"},
    )

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}/reset")
    assert response.status_code == 200, response.text
    reset = response.json()
    assert reset["material"] == default["material"]
    assert reset["dn"] == default["dn"]
    assert reset["pressure_class"] == default["pressure_class"]
    assert reset["forced"] is False


def test_reset_unknown_segment_returns_404(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/does-not-exist/reset")
    assert response.status_code == 404


def test_network_violations_flags_di_increase_downstream(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    mid_pk = trace["length"] / 2
    client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": mid_pk},
    )
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    downstream_segment = max(segments, key=lambda s: s["pk_start"])

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{downstream_segment['id']}",
        json={"dn": 500},
    )

    violations = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/network/violations").json()
    assert any(v["code"] == "DI_INCREASES_DOWNSTREAM" for v in violations)


def test_delete_trace_cascades_nodes_and_segments(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    response = client.delete(f"/api/v1/projects/{session_id}/traces/{trace['id']}")
    assert response.status_code == 204

    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    assert nodes == []
    assert segments == []


def test_add_node_with_type_and_name(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    mid_pk = trace["length"] / 2

    response = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": mid_pk, "type": "reservoir", "name": "Res1"},
    )
    assert response.status_code == 201, response.text
    node = response.json()
    assert node["type"] == "reservoir"
    assert node["name"] == "Res1"


def test_add_node_rejects_unlisted_type(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    response = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": trace["length"] / 2, "type": "high_point"},
    )
    assert response.status_code == 422


def test_delete_non_terminal_node_of_any_type_is_allowed(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    node = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": trace["length"] / 2, "type": "pumping_station", "name": "SP1"},
    ).json()

    response = client.delete(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{node['id']}")
    assert response.status_code == 204


def test_troncons_single_group_when_no_real_ouvrage(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    troncons = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/network/troncons").json()
    assert len(troncons) == 1
    assert troncons[0]["pk_start"] == 0.0
    assert troncons[0]["pk_end"] == trace["length"]


def test_troncons_junction_stays_transparent(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": trace["length"] / 2, "type": "junction"},
    )
    troncons = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/network/troncons").json()
    assert len(troncons) == 1
    assert len(troncons[0]["segment_ids"]) == 2


def test_troncons_split_at_real_ouvrage(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": trace["length"] / 2, "type": "pumping_station", "name": "SP1"},
    )
    troncons = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/network/troncons").json()
    assert len(troncons) == 2
    for t in troncons:
        assert len(t["segment_ids"]) == 1


def test_patch_node_retypes_and_renames_a_terminal_endpoint(client, session_id, project_state, sample_kml_bytes, import_trace):
    # Une extremite de trace doit pouvoir porter un ouvrage (consigne utilisateur, Lot 3 etape 1c).
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    terminal = nodes[0]
    assert terminal["pk"] == 0.0

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{terminal['id']}",
        json={"type": "reservoir", "name": "Res1"},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["type"] == "reservoir"
    assert updated["name"] == "Res1"


def test_retyped_terminal_endpoint_still_cannot_be_deleted(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    terminal = nodes[0]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{terminal['id']}",
        json={"type": "reservoir", "name": "Res1"},
    )
    response = client.delete(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{terminal['id']}")
    assert response.status_code == 400


def test_patch_node_unknown_node_returns_404(client, session_id, project_state):
    variant_id = _default_variant_id(project_state)
    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/does-not-exist",
        json={"type": "reservoir"},
    )
    assert response.status_code == 404
