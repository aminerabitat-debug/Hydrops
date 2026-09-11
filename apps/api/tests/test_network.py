import pytest


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
        json={"material": "FD", "dn": 200, "pressure_class": "K9"},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["material"] == "FD"
    assert updated["dn"] == 200
    assert updated["forced"] is True
    assert updated["di"] == 200.0


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
            "min_velocity": 0.3,
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
    assert updated["min_velocity"] == 0.3


def test_reset_segment_also_clears_hydraulic_fields(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"material": "FD", "dn": 200, "pressure_class": "K9", "max_velocity": 1.5, "min_velocity": 0.3},
    )
    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}/reset")
    assert response.status_code == 200, response.text
    reset = response.json()
    assert reset["forced"] is False
    assert "max_velocity" not in reset
    assert "min_velocity" not in reset


def test_patch_segment_forces_material_dn_resolves_cheapest_pressure_class(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Consigne utilisateur : "fixer des contraintes Materiau et DN au niveau de la fenetre
    # tronçon" — aucune classe de pression demandee, la moins chere disponible pour ce (materiau,
    # DN) est retenue automatiquement.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"forced_material": "PEHD", "forced_dn": 110},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["forced_material"] == "PEHD"
    assert updated["forced_dn"] == 110
    assert updated["material"] == "PEHD"
    assert updated["dn"] == 110
    assert updated["forced"] is True


def test_patch_segment_rejects_unknown_forced_material_dn_combination(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"forced_material": "PEHD", "forced_dn": 999999},
    )
    assert response.status_code == 422


def test_patch_segment_clears_forced_material_dn_with_empty_string(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"forced_material": "PEHD", "forced_dn": 110},
    )

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"forced_material": ""},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert "forced_material" not in updated
    assert "forced_dn" not in updated
    default = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()[0]
    assert default["material"] == "PEHD" and default["dn"] == 160  # catalogue par defaut


def test_reset_segment_clears_forced_material_dn(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"forced_material": "PEHD", "forced_dn": 110},
    )

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}/reset")
    assert response.status_code == 200, response.text
    reset = response.json()
    assert "forced_material" not in reset
    assert "forced_dn" not in reset


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
        json={"material": "FD", "dn": 200, "pressure_class": "K9"},
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
        json={"material": "PVC", "dn": 500, "pressure_class": "PN10"},
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
        json={"trace_id": trace["id"], "pk": mid_pk, "type": "storage_reservoir", "name": "Res1"},
    )
    assert response.status_code == 201, response.text
    node = response.json()
    assert node["type"] == "storage_reservoir"
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
        json={"type": "storage_reservoir", "name": "Res1"},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["type"] == "storage_reservoir"
    assert updated["name"] == "Res1"


def test_retyped_terminal_endpoint_still_cannot_be_deleted(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    terminal = nodes[0]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{terminal['id']}",
        json={"type": "storage_reservoir", "name": "Res1"},
    )
    response = client.delete(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{terminal['id']}")
    assert response.status_code == 400


def test_patch_node_unknown_node_returns_404(client, session_id, project_state):
    variant_id = _default_variant_id(project_state)
    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/does-not-exist",
        json={"type": "storage_reservoir"},
    )
    assert response.status_code == 404


def test_patch_node_type_change_resets_forced_segment_of_its_troncon(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Regime change (reservoir -> station de pompage, gravitaire -> refoulement) sans changement
    # de topologie (le noeud de depart etait deja une frontiere) : le segment de ce troncon, deja
    # valide (forced), doit perdre sa validation et revenir au catalogue par defaut (consigne
    # utilisateur : "réinitialiser les tronçons qui sont impactés").
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    start_node = nodes[0]
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    default_material = segments[0]["material"]
    default_dn = segments[0]["dn"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{start_node['id']}",
        json={"type": "storage_reservoir", "name": "Res1"},
    )
    patched_segment = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"material": "FD", "dn": 200, "pressure_class": "K9"},
    ).json()
    assert patched_segment["forced"] is True

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{start_node['id']}",
        json={"type": "pumping_station", "name": "SP1"},
    )
    assert response.status_code == 200, response.text

    segments_after = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    updated = next(s for s in segments_after if s["id"] == segment_id)
    assert updated["forced"] is False
    assert updated["material"] == default_material
    assert updated["dn"] == default_dn


def test_patch_node_type_change_resets_both_segments_when_troncon_merges(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Un noeud transparent (tie_in) qui devient une frontiere (pressure_break) scinde un troncon en
    # deux ; l'inverse (pressure_break -> tie_in) les fusionne. Les DEUX segments de l'ex-troncon
    # fusionne doivent perdre leur validation, meme si un seul des deux touchait directement le
    # noeud retype de chaque cote (consigne utilisateur).
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    mid_pk = trace["length"] / 2
    middle = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": mid_pk},
    ).json()

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{middle['id']}",
        json={"type": "pressure_break", "name": "BC1"},
    )

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    assert len(segments) == 2
    default_material = segments[0]["material"]
    default_dn = segments[0]["dn"]
    for seg in segments:
        patched = client.patch(
            f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{seg['id']}",
            json={"material": "FD", "dn": 200, "pressure_class": "K9"},
        ).json()
        assert patched["forced"] is True

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{middle['id']}",
        json={"type": "tie_in", "name": ""},
    )
    assert response.status_code == 200, response.text

    segments_after = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    assert len(segments_after) == 2
    for seg in segments_after:
        assert seg["forced"] is False
        assert seg["material"] == default_material
        assert seg["dn"] == default_dn


def test_patch_node_data_change_clears_dimensioning_but_keeps_forced(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Un changement de DATA (ex. fluide) sur un ouvrage — sans changement de TYPE — ne change ni
    # le regime ni la topologie : les parametres hydrauliques saisis (donc `forced`) restent
    # valides, seul le dimensionnement (materiau/DN, qui peut dependre du fluide) n'est plus
    # garanti et doit repasser au catalogue par defaut (consigne utilisateur).
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    start_node = nodes[0]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{start_node['id']}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    default_material = segments[0]["material"]
    default_dn = segments[0]["dn"]
    patched_segment = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "material": "FD", "dn": 200, "pressure_class": "K9",
            "head_flow": 50.0, "min_pressure": 5.0,
        },
    ).json()
    assert patched_segment["forced"] is True

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{start_node['id']}",
        json={"data": {"fluid": "Eau usée brute"}},
    )
    assert response.status_code == 200, response.text

    segments_after = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    updated = next(s for s in segments_after if s["id"] == segment_id)
    assert updated["forced"] is True
    assert updated["material"] == default_material
    assert updated["dn"] == default_dn
    # Les parametres hydrauliques saisis restent intacts (pas un reset complet).
    assert updated["head_flow"] == pytest.approx(50.0)
    assert updated["min_pressure"] == pytest.approx(5.0)


def test_patch_node_position_moves_node_and_adjusts_adjacent_segments(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    mid_pk = trace["length"] / 2
    junction = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": mid_pk},
    ).json()
    new_pk = mid_pk + 5.0

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{junction['id']}/position",
        json={"pk": new_pk},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["node"]["pk"] == pytest.approx(new_pk)
    assert body["needs_level_confirmation"] is False

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    upstream_seg = next(s for s in segments if s["downstream_node_id"] == junction["id"])
    downstream_seg = next(s for s in segments if s["upstream_node_id"] == junction["id"])
    assert upstream_seg["pk_end"] == pytest.approx(new_pk)
    assert downstream_seg["pk_start"] == pytest.approx(new_pk)


def test_patch_node_position_moves_structural_endpoint(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Un reservoir amont demarre presque toujours au premier noeud (structurel) de sa trace — ce
    # cas doit rester deplacable (consigne utilisateur), pas rejete : seules les bornes
    # (voisins immediats de la meme trace) contraignent le deplacement, jamais le type d'extremite.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    new_pk = trace["length"] / 2
    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{nodes[0]['id']}/position",
        json={"pk": new_pk},
    )
    assert response.status_code == 200, response.text
    assert response.json()["node"]["pk"] == pytest.approx(new_pk)


def test_patch_node_position_rejects_pk_beyond_neighbors(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    mid_pk = trace["length"] / 2
    junction = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": mid_pk},
    ).json()
    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{junction['id']}/position",
        json={"pk": trace["length"] + 10.0},
    )
    assert response.status_code == 422


def test_patch_node_position_recomputes_relative_level_offset(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # La cote amont est portee par le segment qui DEMARRE au noeud deplace (le noeud deplace en
    # est le noeud amont) — pas par celui qui s'y termine (qui appartient a un tronçon different).
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    mid_pk = trace["length"] / 2
    junction = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": mid_pk / 2},
    ).json()

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    downstream_segment = next(s for s in segments if s["upstream_node_id"] == junction["id"])
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{downstream_segment['id']}",
        json={"upstream_water_level_min": junction["z"] + 3.0, "upstream_water_level_min_offset": 3.0},
    )

    new_pk = mid_pk / 2 + 10.0
    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{junction['id']}/position",
        json={"pk": new_pk},
    )
    assert response.status_code == 200, response.text
    new_z = response.json()["node"]["z"]

    segments_after = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    updated_downstream_segment = next(s for s in segments_after if s["id"] == downstream_segment["id"])
    assert updated_downstream_segment["upstream_water_level_min"] == pytest.approx(new_z + 3.0)
    assert updated_downstream_segment["upstream_water_level_min_offset"] == pytest.approx(3.0)
