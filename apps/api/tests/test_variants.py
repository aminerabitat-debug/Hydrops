def test_list_variants_returns_default_variant(client, session_id, project_state):
    response = client.get(f"/api/v1/projects/{session_id}/variants")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "Variante 1"


def test_create_additional_variant(client, session_id, project_state):
    response = client.post(f"/api/v1/projects/{session_id}/variants", json={"name": "Variante pompee"})
    assert response.status_code == 200
    assert response.json()["name"] == "Variante pompee"

    response = client.get(f"/api/v1/projects/{session_id}/variants")
    assert len(response.json()) == 2


def test_duplicate_variant_creates_independent_copy(client, session_id, project_state):
    original_id = project_state["variants"][0]["id"]
    response = client.post(f"/api/v1/projects/{session_id}/variants/{original_id}/duplicate")
    assert response.status_code == 200
    copy = response.json()
    assert copy["id"] != original_id
    assert copy["duplicated_from_variant_id"] == original_id
    # Nom non redondant genere automatiquement (consigne utilisateur) — jamais le meme nom que
    # l'original, qui preterait a confusion dans l'arborescence.
    assert copy["name"] == "Variante 1 (copie)"


def test_duplicate_variant_twice_avoids_name_collision(client, session_id, project_state):
    original_id = project_state["variants"][0]["id"]
    first_copy = client.post(f"/api/v1/projects/{session_id}/variants/{original_id}/duplicate").json()
    second_copy = client.post(f"/api/v1/projects/{session_id}/variants/{original_id}/duplicate").json()
    assert first_copy["name"] == "Variante 1 (copie)"
    assert second_copy["name"] == "Variante 1 (copie 2)"
    assert first_copy["name"] != second_copy["name"]


def test_duplicate_unknown_variant_returns_404(client, session_id, project_state):
    response = client.post(f"/api/v1/projects/{session_id}/variants/does-not-exist/duplicate")
    assert response.status_code == 404


def test_delete_variant(client, session_id, project_state):
    original_id = project_state["variants"][0]["id"]
    response = client.delete(f"/api/v1/projects/{session_id}/variants/{original_id}")
    assert response.status_code == 204
    assert client.get(f"/api/v1/projects/{session_id}/variants").json() == []


def test_new_variant_seeds_network_on_existing_traces(client, session_id, project_state, sample_kml_bytes, import_trace):
    # Le trace est importe AVANT la creation de la deuxieme variante — celle-ci doit quand meme
    # obtenir son propre reseau (2 noeuds terminal + 1 segment) dessus, sans import supplementaire.
    import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")

    new_variant = client.post(f"/api/v1/projects/{session_id}/variants", json={"name": "Variante 2"}).json()
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{new_variant['id']}/nodes").json()
    assert len(nodes) == 2
    assert {n["type"] for n in nodes} == {"junction"}


def test_duplicate_variant_copies_its_own_network_independently(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    original_id = project_state["variants"][0]["id"]
    import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    original_segment = client.get(f"/api/v1/projects/{session_id}/variants/{original_id}/segments").json()[0]

    copy = client.post(f"/api/v1/projects/{session_id}/variants/{original_id}/duplicate").json()
    copy_nodes = client.get(f"/api/v1/projects/{session_id}/variants/{copy['id']}/nodes").json()
    copy_segments = client.get(f"/api/v1/projects/{session_id}/variants/{copy['id']}/segments").json()
    assert len(copy_nodes) == 2
    assert len(copy_segments) == 1
    assert copy_segments[0]["id"] != original_segment["id"]  # copie independante, pas une reference

    # Modifier la copie ne doit pas affecter l'originale (V1-03 : duplication integrale et
    # independante).
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{copy['id']}/segments/{copy_segments[0]['id']}",
        json={"dn": 200, "material": "fonte_ductile", "pressure_class": "k9"},
    )
    original_segment_after = client.get(f"/api/v1/projects/{session_id}/variants/{original_id}/segments").json()[0]
    assert original_segment_after["dn"] == original_segment["dn"]


def test_patch_variant_renames_it(client, session_id, project_state):
    original_id = project_state["variants"][0]["id"]
    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{original_id}", json={"name": "Variante Gravitaire"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Variante Gravitaire"

    listed = client.get(f"/api/v1/projects/{session_id}/variants").json()
    assert listed[0]["name"] == "Variante Gravitaire"


def test_patch_variant_rejects_empty_name(client, session_id, project_state):
    original_id = project_state["variants"][0]["id"]
    response = client.patch(f"/api/v1/projects/{session_id}/variants/{original_id}", json={"name": ""})
    assert response.status_code == 422


def test_patch_unknown_variant_returns_404(client, session_id, project_state):
    response = client.patch(f"/api/v1/projects/{session_id}/variants/does-not-exist", json={"name": "X"})
    assert response.status_code == 404


def test_delete_variant_cascades_its_own_nodes_and_segments(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    original_id = project_state["variants"][0]["id"]
    import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    second_variant = client.post(f"/api/v1/projects/{session_id}/variants", json={"name": "Variante 2"}).json()

    client.delete(f"/api/v1/projects/{session_id}/variants/{original_id}")

    # La suppression ne doit affecter QUE le reseau de la variante supprimee, pas celui de l'autre
    # variante sur le meme trace partage.
    remaining_nodes = client.get(f"/api/v1/projects/{session_id}/variants/{second_variant['id']}/nodes").json()
    assert len(remaining_nodes) == 2
