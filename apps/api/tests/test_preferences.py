def test_get_preferences_returns_defaults(client, session_id, project_state):
    response = client.get(f"/api/v1/projects/{session_id}/preferences")
    assert response.status_code == 200
    body = response.json()
    assert body["fluid_temperature_c"] == 20.0
    assert body["singular_loss_markup_pct"] == 10.0
    assert body["roughness_by_material"]["PVC"] == 0.01
    assert len(body["material_criteria"]) > 0
    # Valeurs de depart usuelles (consigne utilisateur) pour prereplir "Modifier le tronçon" tant
    # que l'utilisateur n'a rien saisi de son cote.
    assert body["default_min_pressure"] == 5.0
    assert body["default_downstream_residual_pressure"] == 10.0
    assert body["default_max_velocity"] == 2.0
    assert body["default_min_velocity"] == 0.2


def test_put_preferences_overrides_roughness_and_persists(client, session_id, project_state):
    payload = {
        "roughness_by_material": {"PVC": 0.02},
        "fluid_temperature_c": 15.0,
        "singular_loss_markup_pct": 12.0,
        "material_criteria": [{"dn_min": None, "dn_max": 110, "fluid": None, "materials": ["PEHD"]}],
    }
    response = client.put(f"/api/v1/projects/{session_id}/preferences", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["roughness_by_material"]["PVC"] == 0.02
    assert body["fluid_temperature_c"] == 15.0
    assert len(body["material_criteria"]) == 1

    refetched = client.get(f"/api/v1/projects/{session_id}/preferences").json()
    assert refetched["fluid_temperature_c"] == 15.0
    assert refetched["roughness_by_material"]["PVC"] == 0.02
