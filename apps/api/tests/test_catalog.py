def test_list_materials(client):
    response = client.get("/api/v1/catalog/materials")
    assert response.status_code == 200
    materials = {m["material"] for m in response.json()}
    assert {"PEHD", "PVC", "FD", "FD JV", "BP", "Acier", "PRV"} <= materials


def test_list_pressure_classes(client):
    response = client.get("/api/v1/catalog/pressure-classes", params={"material": "PEHD"})
    assert response.status_code == 200
    assert set(response.json()) == {"PN6", "PN10", "PN16"}


def test_list_pressure_classes_unknown_material(client):
    response = client.get("/api/v1/catalog/pressure-classes", params={"material": "nope"})
    assert response.status_code == 404


def test_list_diameters(client):
    response = client.get(
        "/api/v1/catalog/diameters", params={"material": "PEHD", "pressure_class": "PN10"}
    )
    assert response.status_code == 200
    diameters = response.json()
    assert any(d["dn"] == 160 for d in diameters)
    entry = next(d for d in diameters if d["dn"] == 160)
    assert entry["di"] < entry["de"]


def test_list_diameters_unknown_combination(client):
    response = client.get(
        "/api/v1/catalog/diameters", params={"material": "PEHD", "pressure_class": "K9"}
    )
    assert response.status_code == 404


def test_list_conduites_returns_all_rows_with_active_flag(client):
    response = client.get("/api/v1/catalog/conduites")
    assert response.status_code == 200
    rows = response.json()
    # 327 IDs (avec les 9 trous PEHD) + 69 lignes PRV generees depuis l'Acier a partir du DN300
    assert len(rows) == 387
    assert all(row["active"] is True for row in rows)


def test_patch_conduite_toggles_active_without_removing_row(client):
    response = client.patch("/api/v1/catalog/conduites/1", json={"active": False})
    assert response.status_code == 200
    assert response.json()["active"] is False

    rows = client.get("/api/v1/catalog/conduites").json()
    row = next(r for r in rows if r["id"] == 1)
    assert row["active"] is False

    # remet dans l'etat par defaut pour ne pas affecter d'autres tests partageant le catalogue global
    client.patch("/api/v1/catalog/conduites/1", json={"active": True})


def test_patch_conduite_unknown_row(client):
    response = client.patch("/api/v1/catalog/conduites/999999", json={"active": False})
    assert response.status_code == 404


def test_prv_rows_mirror_acier_from_dn300(client):
    rows = client.get("/api/v1/catalog/conduites").json()
    prv_rows = [r for r in rows if r["material"] == "PRV"]
    acier_rows = {(r["dn"], r["pressure_class"]): r for r in rows if r["material"] == "Acier" and r["dn"] >= 300}
    assert len(prv_rows) == len(acier_rows)
    for prv in prv_rows:
        acier = acier_rows[(prv["dn"], prv["pressure_class"])]
        assert prv["di"] == acier["di"]
        assert prv["pms"] == acier["pms"]
        assert prv["prix_aps"] == acier["prix_aps"]
    assert all(dn >= 300 for dn, _ in acier_rows)
