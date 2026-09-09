def test_list_materials(client):
    response = client.get("/api/v1/catalog/materials")
    assert response.status_code == 200
    materials = {m["material"] for m in response.json()}
    assert {"pehd_pe100", "pvc", "fonte_ductile"} <= materials


def test_list_pressure_classes(client):
    response = client.get("/api/v1/catalog/pressure-classes", params={"material": "pehd_pe100"})
    assert response.status_code == 200
    assert set(response.json()) == {"pn10", "pn16"}


def test_list_pressure_classes_unknown_material(client):
    response = client.get("/api/v1/catalog/pressure-classes", params={"material": "nope"})
    assert response.status_code == 404


def test_list_diameters(client):
    response = client.get(
        "/api/v1/catalog/diameters", params={"material": "pehd_pe100", "pressure_class": "pn10"}
    )
    assert response.status_code == 200
    diameters = response.json()
    assert any(d["dn"] == 160 for d in diameters)
    entry = next(d for d in diameters if d["dn"] == 160)
    assert entry["di"] < entry["de"]


def test_list_diameters_unknown_combination(client):
    response = client.get(
        "/api/v1/catalog/diameters", params={"material": "pehd_pe100", "pressure_class": "k9"}
    )
    assert response.status_code == 404
