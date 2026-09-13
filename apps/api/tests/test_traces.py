import pytest


def _default_variant_id(project_state) -> str:
    return project_state["variants"][0]["id"]


def test_import_returns_job_id_immediately(client, session_id, project_state, sample_kml_bytes):
    response = client.post(
        f"/api/v1/projects/{session_id}/traces/import",
        files={"file": ("sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["total_chunks"] >= 1


def test_import_job_status_reaches_done_with_trace(client, session_id, project_state, sample_kml_bytes, import_trace):
    trace = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")

    assert trace["source"] == "kml_import"
    assert trace["length"] > 0
    assert len(trace["geometry"]["coordinates"]) == 5
    assert trace["project_id"] == project_state["project"]["id"]

    profile = trace["elevation_profile"]
    assert profile["dem_source"] == "synthetic"
    assert len(profile["raw"]) > 1
    assert len(profile["smoothed"]) == len(profile["raw"])
    # PK strictement croissant sur le profil brut (V1-01/V1-02 : coherence du profil)
    pks = [p["pk"] for p in profile["raw"]]
    assert pks == sorted(pks)


def test_import_job_status_reports_completed_chunks_at_end(client, session_id, project_state, sample_kml_bytes, import_trace):
    import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")

    response = client.post(
        f"/api/v1/projects/{session_id}/traces/import",
        files={"file": ("sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    job_id = response.json()["job_id"]
    import time

    for _ in range(200):
        job = client.get(f"/api/v1/projects/{session_id}/traces/import-jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.02)
    assert job["status"] == "done"
    assert job["completed_chunks"] == job["total_chunks"] > 0


def test_import_job_unknown_id_returns_404(client, session_id, project_state):
    response = client.get(f"/api/v1/projects/{session_id}/traces/import-jobs/does-not-exist")
    assert response.status_code == 404


def test_import_kmz_extracts_inner_kml(client, session_id, project_state, sample_kmz_bytes, import_trace):
    trace = import_trace(session_id, "sample_trace.kmz", sample_kmz_bytes, "application/vnd.google-earth.kmz")
    assert trace["source"] == "kmz_import"


def test_import_rejects_multiple_linestrings(client, session_id, project_state, branched_kml_bytes):
    # Erreur de format KML : validee de facon synchrone, avant meme la creation d'un job.
    response = client.post(
        f"/api/v1/projects/{session_id}/traces/import",
        files={"file": ("branched.kml", branched_kml_bytes, "application/vnd.google-earth.kml+xml")},
    )
    assert response.status_code == 422
    assert "LineString" in response.json()["detail"]


def test_import_seeds_every_existing_variant(client, session_id, project_state, sample_kml_bytes, import_trace):
    # Une deuxieme variante existe deja avant l'import : le trace, partage au niveau projet, doit
    # seeder un reseau (2 noeuds terminal + 1 segment) pour CHAQUE variante existante, pas
    # seulement la premiere.
    second_variant = client.post(f"/api/v1/projects/{session_id}/variants", json={"name": "Variante 2"}).json()
    import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")

    for variant_id in (_default_variant_id(project_state), second_variant["id"]):
        nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
        assert len(nodes) == 2, f"variante {variant_id} devrait avoir 2 noeuds terminal"


def test_get_trace_returns_stored_geometry(client, session_id, project_state, sample_kml_bytes, import_trace):
    imported = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")

    response = client.get(f"/api/v1/projects/{session_id}/traces/{imported['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == imported["id"]


def test_add_crossing_manual_projects_position_from_pk(client, session_id, project_state, sample_kml_bytes, import_trace):
    trace = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    response = client.post(
        f"/api/v1/projects/{session_id}/traces/{trace['id']}/crossings",
        json={"kind": "highway", "pk": 100.0, "label": "Piste locale"},
    )
    assert response.status_code == 200, response.text
    crossings = response.json()["crossings"]
    assert len(crossings) == 1
    added = crossings[0]
    assert added["kind"] == "highway"
    assert added["label"] == "Piste locale"
    assert added["source"] == "manual"
    assert added["pk"] == pytest.approx(100.0)
    # lon/lat projetes sur la geometrie de la trace, jamais (0, 0) ou une valeur arbitraire.
    assert added["lon"] != 0.0 or added["lat"] != 0.0


def test_patch_crossing_updates_fields_and_recomputes_position_on_pk_change(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    trace = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    added = client.post(
        f"/api/v1/projects/{session_id}/traces/{trace['id']}/crossings",
        json={"kind": "highway", "pk": 100.0},
    ).json()["crossings"][0]

    response = client.patch(
        f"/api/v1/projects/{session_id}/traces/{trace['id']}/crossings/{added['id']}",
        json={"kind": "waterway", "pk": 200.0, "label": "Oued"},
    )
    assert response.status_code == 200, response.text
    updated = next(c for c in response.json()["crossings"] if c["id"] == added["id"])
    assert updated["kind"] == "waterway"
    assert updated["label"] == "Oued"
    assert updated["pk"] == pytest.approx(200.0)
    assert (updated["lon"], updated["lat"]) != (added["lon"], added["lat"])


def test_delete_crossing_removes_it(client, session_id, project_state, sample_kml_bytes, import_trace):
    trace = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    added = client.post(
        f"/api/v1/projects/{session_id}/traces/{trace['id']}/crossings",
        json={"kind": "building", "pk": 50.0},
    ).json()["crossings"][0]

    response = client.delete(f"/api/v1/projects/{session_id}/traces/{trace['id']}/crossings/{added['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["crossings"] == []


def test_delete_crossing_unknown_id_returns_404(client, session_id, project_state, sample_kml_bytes, import_trace):
    trace = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    response = client.delete(f"/api/v1/projects/{session_id}/traces/{trace['id']}/crossings/does-not-exist")
    assert response.status_code == 404


def test_detect_crossings_preserves_manual_ones(client, session_id, project_state, sample_kml_bytes, import_trace, monkeypatch):
    # Consigne utilisateur : une traversee ajoutee manuellement ne doit jamais etre ecrasee par une
    # redetection Overpass ulterieure.
    trace = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    client.post(
        f"/api/v1/projects/{session_id}/traces/{trace['id']}/crossings",
        json={"kind": "building", "pk": 10.0, "label": "Repère manuel"},
    )

    import hydrops_api.routers.traces as traces_router

    async def _fake_fetch_osm_features(bbox):
        return []

    monkeypatch.setattr(traces_router.crossings_service, "fetch_osm_features", _fake_fetch_osm_features)

    response = client.post(f"/api/v1/projects/{session_id}/traces/{trace['id']}/crossings/detect")
    assert response.status_code == 200, response.text
    crossings = response.json()["crossings"]
    assert len(crossings) == 1
    assert crossings[0]["source"] == "manual"
    assert crossings[0]["label"] == "Repère manuel"


def test_list_traces_returns_project_level_traces(client, session_id, project_state, sample_kml_bytes, import_trace):
    imported = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    response = client.get(f"/api/v1/projects/{session_id}/traces")
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [imported["id"]]


def test_patch_trace_reverses_direction(client, session_id, project_state, sample_kml_bytes, import_trace):
    imported = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    assert imported["hydraulic_direction"] == "as_drawn"

    response = client.patch(
        f"/api/v1/projects/{session_id}/traces/{imported['id']}",
        json={"hydraulic_direction": "reversed"},
    )
    assert response.status_code == 200
    assert response.json()["hydraulic_direction"] == "reversed"


def test_delete_trace_cascades_nodes_for_every_variant(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id = _default_variant_id(project_state)
    imported = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")

    response = client.delete(f"/api/v1/projects/{session_id}/traces/{imported['id']}")
    assert response.status_code == 204

    assert client.get(f"/api/v1/projects/{session_id}/traces/{imported['id']}").status_code == 404
    assert client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json() == []
