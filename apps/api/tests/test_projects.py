def test_new_project_creates_project_and_default_variant(project_state):
    assert project_state["project"]["name"] == "Projet Test"
    assert len(project_state["variants"]) == 1
    assert project_state["variants"][0]["name"] == "Variante 1"
    assert project_state["traces"] == []


def test_new_project_requires_existing_session(client):
    response = client.post("/api/v1/projects/new?session_id=inconnue", json={"name": "X"})
    assert response.status_code == 404


def test_new_project_default_annual_volume_is_constant(project_state):
    assert project_state["project"]["annual_volume"]["mode"] == "constant"


def test_new_project_with_variable_volume_points(client, session_id):
    response = client.post(
        f"/api/v1/projects/new?session_id={session_id}",
        json={
            "name": "Projet Volume Variable",
            "commissioning_year": 2028,
            "amortization_years": 3,
            "annual_volume_points": [
                {"year": 2028, "value": 10.0},
                {"year": 2029, "value": 12.0},
                {"year": 2030, "value": 15.0},
            ],
        },
    )
    assert response.status_code == 200
    volume = response.json()["project"]["annual_volume"]
    assert volume["mode"] == "table"
    assert [p["year"] for p in volume["points"]] == [2028, 2029, 2030]


def test_get_project_without_open_project_returns_409(client, session_id):
    response = client.get(f"/api/v1/projects/{session_id}")
    assert response.status_code == 409


def _full_form(**overrides) -> dict:
    payload = {
        "name": "Projet Test",
        "client": "Nouveau Client",
        "discount_rate": 0.08,
    }
    payload.update(overrides)
    return payload


def test_patch_project_updates_fields(client, session_id, project_state):
    response = client.patch(f"/api/v1/projects/{session_id}", json=_full_form())
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["client"] == "Nouveau Client"
    assert body["project"]["discount_rate"] == 0.08
    assert body["project"]["name"] == "Projet Test"


def test_patch_project_phasing_disabled_by_default(client, session_id, project_state):
    assert project_state["project"]["phasing_enabled"] is False
    assert project_state["project"]["phases"] == []


def test_patch_project_accepts_valid_phasing(client, session_id, project_state):
    # Defaut ProjectFormFields : first_investment_year=2026, amortization_years=25 (fenetre
    # jusqu'a 2051) — phase 2 bien apres le 1er investissement, mise en service ulterieure,
    # dans la fenetre d'amortissement.
    response = client.patch(
        f"/api/v1/projects/{session_id}",
        json=_full_form(
            phasing_enabled=True,
            phases=[{"id": "p2", "index": 2, "investment_year": 2030, "commissioning_year": 2032}],
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()["project"]
    assert body["phasing_enabled"] is True
    assert body["phases"] == [{"id": "p2", "index": 2, "investment_year": 2030, "commissioning_year": 2032}]


def test_patch_project_rejects_phase_investment_not_after_previous(client, session_id, project_state):
    # Phase 2 investie la MEME annee (ou avant) que le 1er investissement (2026, defaut) —
    # consigne utilisateur : "Phase 2 doit être ultérieure à phase 1".
    response = client.patch(
        f"/api/v1/projects/{session_id}",
        json=_full_form(
            phasing_enabled=True,
            phases=[{"id": "p2", "index": 2, "investment_year": 2026, "commissioning_year": 2030}],
        ),
    )
    assert response.status_code == 422
    assert "postérieure" in response.json()["detail"].lower()


def test_patch_project_rejects_commissioning_before_investment(client, session_id, project_state):
    # Consigne utilisateur : "année de mise en service doit être ultérieur à année d'investissement".
    response = client.patch(
        f"/api/v1/projects/{session_id}",
        json=_full_form(
            phasing_enabled=True,
            phases=[{"id": "p2", "index": 2, "investment_year": 2030, "commissioning_year": 2029}],
        ),
    )
    assert response.status_code == 422
    assert "mise en service" in response.json()["detail"].lower()


def test_patch_project_rejects_phase_beyond_amortization_window(client, session_id, project_state):
    # Consigne utilisateur : "le tout doit s'intégrer dans la durée d'amortissement" — defaut
    # first_investment_year=2026 + amortization_years=25 = fenetre jusqu'a 2051.
    response = client.patch(
        f"/api/v1/projects/{session_id}",
        json=_full_form(
            phasing_enabled=True,
            phases=[{"id": "p2", "index": 2, "investment_year": 2049, "commissioning_year": 2060}],
        ),
    )
    assert response.status_code == 422
    assert "amortissement" in response.json()["detail"].lower()


def test_patch_project_rejects_second_phase_investment_not_after_first(client, session_id, project_state):
    # Deux phases : la 3e doit etre ulterieure a la 2e, pas seulement a la phase 1 implicite.
    response = client.patch(
        f"/api/v1/projects/{session_id}",
        json=_full_form(
            phasing_enabled=True,
            phases=[
                {"id": "p2", "index": 2, "investment_year": 2030, "commissioning_year": 2032},
                {"id": "p3", "index": 3, "investment_year": 2030, "commissioning_year": 2033},
            ],
        ),
    )
    assert response.status_code == 422


def test_patch_project_preserves_fields_outside_the_form(client, session_id, project_state):
    # "description" n'est pas un champ du formulaire "Parametres du projet" — une edition ne doit
    # pas l'effacer silencieusement si une PATCH precedente ou l'import l'avait renseigne.
    client.patch(f"/api/v1/projects/{session_id}", json=_full_form(client="Premier Client"))
    response = client.patch(f"/api/v1/projects/{session_id}", json=_full_form(client="Deuxieme Client"))
    assert response.status_code == 200
    assert response.json()["project"]["client"] == "Deuxieme Client"


def test_patch_project_rejects_invalid_value(client, session_id, project_state):
    response = client.patch(f"/api/v1/projects/{session_id}", json=_full_form(discount_rate=5.0))
    assert response.status_code == 422


def test_patch_project_rejects_missing_required_name(client, session_id, project_state):
    response = client.patch(f"/api/v1/projects/{session_id}", json={"discount_rate": 0.08})
    assert response.status_code == 422


def test_patch_project_with_variable_volume_points(client, session_id, project_state):
    response = client.patch(
        f"/api/v1/projects/{session_id}",
        json=_full_form(
            amortization_years=2,
            annual_volume_points=[{"year": 2028, "value": 5.0}, {"year": 2029, "value": 6.0}],
        ),
    )
    assert response.status_code == 200
    volume = response.json()["project"]["annual_volume"]
    assert volume["mode"] == "table"
    assert len(volume["points"]) == 2
