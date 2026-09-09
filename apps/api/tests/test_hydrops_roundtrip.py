"""Parcours complet Lot 1 : creer projet -> importer KML -> sauvegarder .hydrops -> rouvrir .hydrops
dans une session distincte et retrouver exactement le meme etat (V1-03 esprit, V1-01, V1-11)."""


def test_save_then_reopen_hydrops_preserves_project_and_trace(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id = project_state["variants"][0]["id"]
    imported_trace = import_trace(
        session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml"
    )

    export_response = client.get(f"/api/v1/projects/{session_id}/export")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/zip"
    hydrops_bytes = export_response.content

    # Nouvelle session independante ("rouvrir .hydrops" depuis zero, comme un nouvel onglet)
    new_session_id = client.post("/api/v1/sessions").json()["session_id"]
    reopen_response = client.post(
        f"/api/v1/projects/import?session_id={new_session_id}",
        files={"file": ("Projet_Test.hydrops", hydrops_bytes, "application/zip")},
    )
    assert reopen_response.status_code == 200
    reopened = reopen_response.json()

    assert reopened["project"]["name"] == project_state["project"]["name"]
    assert reopened["project"]["id"] == project_state["project"]["id"]
    assert len(reopened["traces"]) == 1
    assert reopened["traces"][0]["id"] == imported_trace["id"]
    assert reopened["traces"][0]["geometry"]["coordinates"] == imported_trace["geometry"]["coordinates"]
    assert reopened["traces"][0]["elevation_profile"]["raw"] == imported_trace["elevation_profile"]["raw"]

    # Le trace est partage au niveau projet ; le reseau noeuds/segments de la variante (seede a
    # l'import) doit lui aussi survivre au roundtrip .hydrops.
    reopened_nodes = client.get(f"/api/v1/projects/{new_session_id}/variants/{variant_id}/nodes").json()
    assert len(reopened_nodes) == 2
    assert {n["type"] for n in reopened_nodes} == {"junction"}


def test_reopen_rejects_corrupted_hydrops(client, session_id):
    response = client.post(
        f"/api/v1/projects/import?session_id={session_id}",
        files={"file": ("broken.hydrops", b"not a zip file at all", "application/zip")},
    )
    assert response.status_code == 422


def test_export_without_open_project_returns_409(client, session_id):
    response = client.get(f"/api/v1/projects/{session_id}/export")
    assert response.status_code == 409
