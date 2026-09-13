import pytest


def _default_variant_id(project_state) -> str:
    return project_state["variants"][0]["id"]


def _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id = _default_variant_id(project_state)
    trace = import_trace(session_id, "sample_trace.kml", sample_kml_bytes, "application/vnd.google-earth.kml+xml")
    return variant_id, trace


def test_calcul_rejected_when_troncon_not_validated(client, session_id, project_state, sample_kml_bytes, import_trace):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 409
    assert "tronçon" in response.json()["detail"].lower() or "troncon" in response.json()["detail"].lower()


def test_calcul_rejected_when_regime_indetermine_even_if_forced(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"upstream_water_level_max": 200.0, "upstream_water_level_min": 195.0, "max_velocity": 2.0},
    )
    # Aucun des deux noeuds n'a ete affecte a un ouvrage reel -> regime reste indetermine malgre
    # "forced" (consigne utilisateur : les deux conditions sont requises).
    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 409


def test_calcul_gravitaire_happy_path_sizes_segment_and_writes_results(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    upstream_id, downstream_id = nodes[0]["id"], nodes[1]["id"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{upstream_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC1"},
    )

    max_z = max(n["z"] for n in nodes)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    patch_response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "head_flow": 100.0,
            "upstream_water_level_max": max_z + 60.0,
            "upstream_water_level_min": max_z + 55.0,
            "min_pressure": 5.0,
            "downstream_residual_pressure": 5.0,
            "max_velocity": 2.0,
        },
    )
    assert patch_response.status_code == 200, patch_response.text

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "calculated"
    assert body["segments_updated"] == 1
    assert body["nodes_updated"] == 2

    updated_segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    seg = updated_segments[0]
    # Le debit de tete (100 m3/h, sans piquage sur ce troncon) doit se retrouver tel quel sur le
    # segment, et produire une vitesse/perte de charge non nulles (contrairement au cas Q=0).
    assert seg["flow"] == pytest.approx(100.0)
    assert seg["velocity"] is not None and 0 < seg["velocity"] <= 2.0 + 1e-6
    assert seg["head_loss_unit"] is not None and seg["head_loss_unit"] > 0
    assert seg["head_loss_segment"] is not None and seg["head_loss_segment"] > 0
    # Le troncon est desormais subdivise en piquets fins (glossaire Piquet/Segment/Troncon) : le
    # DN est un tableau (`segment_details`, un par piquet), et les champs scalaires ci-dessus
    # refletent seulement le DERNIER piquet (le plus aval) — sa perte de charge cumulee (depuis le
    # DEBUT du troncon) peut donc legitimement depasser sa propre perte de charge (juste ce dernier
    # piquet), contrairement a l'ancien comportement (un seul segment = cumulee toujours egale a
    # elle-meme).
    assert seg["segment_details"] and len(seg["segment_details"]) >= 1
    last_detail = seg["segment_details"][-1]
    assert last_detail["dn"] == seg["dn"]
    assert last_detail["head_loss_cumulative"] == pytest.approx(seg["head_loss_cumulative"])
    assert seg["head_loss_cumulative"] == pytest.approx(
        sum(d["head_loss_segment"] for d in seg["segment_details"])
    )
    assert seg["head_loss_cumulative"] >= seg["head_loss_segment"] - 1e-9

    updated_nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    downstream_node = next(n for n in updated_nodes if n["id"] == downstream_id)
    assert downstream_node["pressure_dynamic"] is not None
    assert downstream_node["pressure_dynamic"] >= 5.0 - 1e-6
    assert downstream_node["pressure_static_max"] is not None
    assert downstream_node["pressure_static_min"] is not None

    variant = client.get(f"/api/v1/projects/{session_id}").json()["variants"][0]
    assert variant["status"] == "calculated"

    # Toute modification des donnees du troncon doit invalider (remettre a None) les resultats du
    # calcul precedent — consigne utilisateur : les colonnes "depuis Debit vers la droite" du
    # profil Data ne doivent jamais rester prereplies avec un resultat perime.
    repatch = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"max_velocity": 1.5},
    )
    assert repatch.status_code == 200, repatch.text
    reset_seg = repatch.json()
    assert reset_seg.get("velocity") is None
    assert reset_seg.get("head_loss_unit") is None
    assert reset_seg.get("head_loss_segment") is None
    assert reset_seg.get("head_loss_cumulative") is None
    assert reset_seg.get("segment_details") is None
    assert reset_seg["flow"] == 0.0

    nodes_after_repatch = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    downstream_after = next(n for n in nodes_after_repatch if n["id"] == downstream_id)
    assert downstream_after.get("piezo_head") is None
    assert downstream_after.get("pressure_dynamic") is None
    assert downstream_after.get("pressure_static_max") is None
    assert downstream_after.get("pressure_static_min") is None

    # Le materiau/DN aussi doivent revenir au catalogue par defaut (pas rester sur le
    # dimensionnement du calcul precedent) — consigne utilisateur : une edition pure des
    # parametres hydrauliques (pas de materiau/dn/classe dans ce payload) invalide le
    # dimensionnement affiche, il ne doit pas persister silencieusement.
    default_material, default_dn = reset_seg["material"], reset_seg["dn"]
    assert (default_material, default_dn) != (seg["material"], seg["dn"])


def test_patch_segment_manual_pipe_correction_is_not_reset_to_default(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # A l'inverse : un payload qui fournit explicitement material/dn/pressure_class est une
    # correction manuelle intentionnelle (depuis le profil Data) — elle doit etre appliquee telle
    # quelle, pas ecrasee par le catalogue par defaut.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    default = segments[0]
    other_dn = next(d for d in [110, 160, 200] if d != default["dn"]) if default["dn"] in [110, 160, 200] else 160

    response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={"material": default["material"], "dn": other_dn, "pressure_class": default["pressure_class"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["dn"] == other_dn


def test_calcul_gravitaire_hydrostatic_alert_clears_segment_and_nodes_but_keeps_forced(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Consigne utilisateur : un troncon dont le calcul produit une alerte n'a "pas abouti sans
    # erreur" — aucune donnee de dimensionnement/pression periee ne doit rester affichee, mais les
    # parametres hydrauliques SAISIS (donc `forced`) restent valides pour un nouvel essai.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    upstream_id, downstream_id = nodes[0]["id"], nodes[1]["id"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{upstream_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC1"},
    )

    trace_detail = client.get(f"/api/v1/projects/{session_id}/traces/{trace['id']}").json()
    raw_profile = trace_detail["elevation_profile"]["raw"]
    min_z = min(p["z"] for p in raw_profile)
    max_z = max(p["z"] for p in raw_profile)
    assert max_z > min_z, "profil de test plat — impossible de forcer l'alerte hydrostatique"
    # Niveau du reservoir a peine au-dessus du terrain le plus bas -> une partie du profil (le
    # point le plus haut) depasse forcement cette cote.
    hydrostatic_level = min_z + 0.01

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "head_flow": 100.0,
            "upstream_water_level_max": hydrostatic_level + 0.5,
            "upstream_water_level_min": hydrostatic_level,
            "min_pressure": 5.0,
            "downstream_residual_pressure": 5.0,
            "max_velocity": 2.0,
        },
    )

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["segments_updated"] == 0
    assert body["nodes_updated"] == 0
    assert any("hydrostatique" in a.lower() for a in body["alerts"])
    # Le reservoir est a l'extremite structurelle de la trace (pk 0) — c'est le cas le plus
    # frequent en pratique pour un reservoir amont, il reste deplacable (consigne utilisateur) :
    # une suggestion doit etre proposee, pas seulement pour un reservoir en noeud interieur.
    assert len(body["reposition_suggestions"]) == 1
    suggestion = body["reposition_suggestions"][0]
    assert suggestion["node_id"] == upstream_id
    assert suggestion["current_pk"] == pytest.approx(0.0)
    assert suggestion["candidate_pk"] != suggestion["current_pk"]


def test_calcul_forced_material_dn_applies_despite_violated_constraints(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Consigne utilisateur : "fixer des contraintes Materiau et DN au niveau de la fenetre
    # tronçon [...] le calcul hydraulique doit se faire meme si certaines contraintes de pression
    # et de vitesse sont violees" — DN110 force est bien trop petit pour ce debit : la vitesse
    # depasse largement la vitesse max demandee, mais le calcul s'applique quand meme (segments et
    # noeuds mis a jour, jamais reinitialises comme pour un dimensionnement automatique en echec).
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    upstream_id, downstream_id = nodes[0]["id"], nodes[1]["id"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{upstream_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC1"},
    )

    trace_detail = client.get(f"/api/v1/projects/{session_id}/traces/{trace['id']}").json()
    max_z = max(p["z"] for p in trace_detail["elevation_profile"]["raw"])

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "head_flow": 300.0,
            "upstream_water_level_max": max_z + 51.0,
            "upstream_water_level_min": max_z + 50.0,  # large marge -> pas d'alerte hydrostatique
            "min_pressure": 5.0,
            "downstream_residual_pressure": 10.0,
            "max_velocity": 0.5,  # DN110 le violera largement, garanti
            "forced_material": "PEHD",
            "forced_dn": 110,
        },
    )

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["segments_updated"] == 1
    assert body["nodes_updated"] == 2
    assert any("vitesse" in a.lower() for a in body["alerts"])

    updated_segment = client.get(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments"
    ).json()[0]
    assert updated_segment["material"] == "PEHD"
    assert updated_segment["dn"] == 110
    assert updated_segment["velocity"] is not None  # calcul reellement applique, pas reinitialise
    # Un pipe force reste homogene sur toute sa longueur — meme subdivise en plusieurs piquets fins
    # (consigne utilisateur : contraintes par plage de PK, toujours subdivise desormais), chaque
    # entree du tableau resout a la MEME valeur puisque la contrainte n'a pas de bornes de PK.
    assert updated_segment["segment_details"] is not None
    assert len(updated_segment["segment_details"]) >= 1
    assert all(d["material"] == "PEHD" and d["dn"] == 110 for d in updated_segment["segment_details"])


def test_calcul_gravitaire_single_segment_troncon_gets_per_piquet_segment_details(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Reproduit le constat du cas KMZ fourni par l'utilisateur : un troncon gravitaire SANS noeud
    # reel intermediaire (un seul Segment persiste) doit tout de meme etre dimensionne piquet par
    # piquet (glossaire Piquet/Segment/Troncon) — pas une seule "case" de DN pour tout le troncon.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    upstream_id, downstream_id = nodes[0]["id"], nodes[1]["id"]

    # Pas hydraulique reduit (defaut 200 m) pour garantir plusieurs piquets fins sur la trace de
    # test (~2 km) — Preferences, consigne utilisateur : point de depart editable.
    prefs = client.get(f"/api/v1/projects/{session_id}/preferences").json()
    prefs["hydraulic_segment_step_m"] = 50.0
    put_response = client.put(f"/api/v1/projects/{session_id}/preferences", json=prefs)
    assert put_response.status_code == 200, put_response.text

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{upstream_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC1"},
    )

    max_z = max(n["z"] for n in nodes)
    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "head_flow": 100.0,
            "upstream_water_level_max": max_z + 60.0,
            "upstream_water_level_min": max_z + 55.0,
            "min_pressure": 5.0,
            "downstream_residual_pressure": 5.0,
            "max_velocity": 2.0,
        },
    )

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text
    assert response.json()["segments_updated"] == 1

    seg = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()[0]
    details = seg["segment_details"]
    assert details is not None and len(details) > 1, (
        "un seul Segment persiste sans noeud reel intermediaire doit quand meme etre subdivise en "
        "plusieurs piquets fins pour le calcul (sinon aucune optimisation de DN par piquet n'est "
        "possible, cf. cas KMZ fourni par l'utilisateur)"
    )
    # Ordre amont -> aval, PK strictement croissant, et DN jamais croissant vers l'aval (le meme
    # plancher que la contrainte de non-croissance deja verifiee au niveau de l'optimisation
    # telescopique du moteur, ici observee de bout en bout via l'API).
    pks = [d["pk"] for d in details]
    assert pks == sorted(pks)
    dns = [d["dn"] for d in details]
    assert all(dns[i] >= dns[i + 1] for i in range(len(dns) - 1))
    assert details[-1]["pk"] == pytest.approx(seg["pk_end"])
    assert details[-1]["dn"] == seg["dn"]


def test_calcul_new_unbounded_constraint_overrides_legacy_forced_material(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Compatibilite ascendante (consigne utilisateur) : l'ancien forced_material/forced_dn reste lu
    # (contrainte implicite sans bornes), mais une NOUVELLE contrainte non bornee ajoutee depuis le
    # panneau Contraintes sur le MEME champ doit pouvoir le remplacer — sinon un projet existant
    # serait bloque avec son ancien materiau sans aucun moyen de le changer depuis la nouvelle UI.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    upstream_id, downstream_id = nodes[0]["id"], nodes[1]["id"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{upstream_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC1"},
    )
    max_z = max(n["z"] for n in nodes)
    segment_id = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "head_flow": 100.0,
            "upstream_water_level_max": max_z + 60.0,
            "upstream_water_level_min": max_z + 55.0,
            "max_velocity": 2.0,
            "forced_material": "PEHD",
            "forced_dn": 110,
        },
    )
    # Nouvelle contrainte non bornee sur LES DEUX champs (materiau ET DN) — evite de melanger un
    # materiau neuf avec le DN de l'ancien forçage si cette combinaison n'existe pas au catalogue
    # (FD/100 existe bien, cf. test_calcul_forced_material_dn_applies_despite_violated_constraints
    # pour PEHD/110).
    constraints_response = client.put(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}/constraints",
        json={"constraints": [{"material": "FD", "dn": 100}]},
    )
    assert constraints_response.status_code == 200, constraints_response.text

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text

    seg = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()[0]
    assert seg["material"] == "FD"
    assert seg["dn"] == 100
    assert all(d["material"] == "FD" and d["dn"] == 100 for d in seg["segment_details"])


def test_calcul_applies_per_pk_range_constraint_over_wider_material_constraint(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Reproduit l'exemple donne par l'utilisateur : "fixer le materiau a FD sur tout le tronçon et
    # DN500 [ici DN60, present au catalogue par defaut] entre pk 500 et pk 700" — deux contraintes
    # distinctes, chacune ne renseignant qu'un champ, qui se combinent (glossaire Piquet/Segment/
    # Troncon : le DN d'un tronçon est un tableau, une valeur par piquet).
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    upstream_id, downstream_id = nodes[0]["id"], nodes[1]["id"]

    prefs = client.get(f"/api/v1/projects/{session_id}/preferences").json()
    prefs["hydraulic_segment_step_m"] = 50.0
    assert client.put(f"/api/v1/projects/{session_id}/preferences", json=prefs).status_code == 200

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{upstream_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC1"},
    )

    max_z = max(n["z"] for n in nodes)
    segment_id = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "head_flow": 100.0,
            "upstream_water_level_max": max_z + 60.0,
            "upstream_water_level_min": max_z + 55.0,
            "max_velocity": 2.0,
        },
    )
    constraints_response = client.put(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}/constraints",
        json={"constraints": [{"material": "FD"}, {"dn": 60, "pk_start": 500.0, "pk_end": 700.0}]},
    )
    assert constraints_response.status_code == 200, constraints_response.text

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text
    assert response.json()["segments_updated"] == 1

    details = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()[0]["segment_details"]
    assert details, "aucun detail par piquet retourne"
    assert all(d["material"] == "FD" for d in details), "le materiau doit rester FD sur tout le tronçon"
    inside_window = [d for d in details if 500.0 - 1e-6 <= d["pk"] <= 700.0 + 1e-6]
    outside_window = [d for d in details if d["pk"] < 500.0 - 1e-6 or d["pk"] > 700.0 + 1e-6]
    assert inside_window, "aucun piquet dans la fenetre 500-700 — pas hydraulique trop grossier ?"
    assert all(d["dn"] == 60 for d in inside_window)
    assert outside_window and any(d["dn"] != 60 for d in outside_window), (
        "hors de la fenetre 500-700, le DN doit rester choisi automatiquement (pas fige a 60)"
    )


def test_calcul_min_pressure_exclusion_zone_is_informative_not_blocking(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Consigne utilisateur : "Zone d'exclusion de la contrainte de pression min" — propre au
    # tronçon, en METRES depuis l'ouvrage de depart (Segment.min_pressure_exclusion_m) — ou
    # min_pressure n'est plus opposable, une alerte informative le signale mais le calcul
    # s'applique quand meme.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    upstream_id, downstream_id = nodes[0]["id"], nodes[1]["id"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{upstream_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC1"},
    )

    trace_detail = client.get(f"/api/v1/projects/{session_id}/traces/{trace['id']}").json()
    max_z = max(p["z"] for p in trace_detail["elevation_profile"]["raw"])
    level = max_z + 50.0  # large marge -> pas d'alerte hydrostatique

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "head_flow": 100.0,
            "upstream_water_level_max": level + 1.0,
            "upstream_water_level_min": level,
            "min_pressure": 1000.0,  # bien plus que la marge disponible partout -> viole toujours
            "max_velocity": 2.0,
            "min_pressure_exclusion_m": 999999.0,  # tout le tronçon exclu de min_pressure
        },
    )

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["segments_updated"] == 1
    assert body["nodes_updated"] == 2
    assert not any("pression insuffisante" in a.lower() for a in body["alerts"])
    assert any("zone d'exclusion" in a.lower() for a in body["alerts"])

    updated_segment = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()[0]
    assert updated_segment["velocity"] is not None  # calcul reellement applique, pas reinitialise


def test_calcul_min_pressure_shortfall_is_informative_not_blocking(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Consigne utilisateur : "ne bloque plus le calcul pour une question de pression minimale,
    # affiche juste une alerte" — un manque de pression residuelle/min (hors alerte hydrostatique,
    # qui n'a aucun resultat exploitable) ne doit plus reinitialiser le tronçon : le dimensionnement
    # calcule reste applique, l'alerte reste seulement informative.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    upstream_id, downstream_id = nodes[0]["id"], nodes[1]["id"]

    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{upstream_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC1"},
    )

    trace_detail = client.get(f"/api/v1/projects/{session_id}/traces/{trace['id']}").json()
    max_z = max(p["z"] for p in trace_detail["elevation_profile"]["raw"])
    level = max_z + 5.0  # marge de niveau modeste -> pas d'alerte hydrostatique, mais pression serree

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    segment_id = segments[0]["id"]
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{segment_id}",
        json={
            "head_flow": 100.0,
            "upstream_water_level_max": level + 1.0,
            "upstream_water_level_min": level,
            "min_pressure": 1000.0,  # bien plus que la marge disponible -> viole partout, sans exclusion
            "max_velocity": 2.0,
        },
    )

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text
    body = response.json()
    assert not any("hydrostatique" in a.lower() for a in body["alerts"])
    assert any("pression insuffisante" in a.lower() for a in body["alerts"])
    assert body["segments_updated"] == 1
    assert body["nodes_updated"] == 2

    updated_segment = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()[0]
    assert updated_segment["velocity"] is not None  # calcul applique malgre l'alerte, pas reinitialise


def test_calcul_scoped_to_one_troncon_ignores_other_unvalidated_troncons(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Consigne utilisateur : un tronçon deja selectionne et valide se calcule seul, sans exiger que
    # les AUTRES tronçons de la variante soient valides — a l'inverse du calcul non scope (variante
    # selectionnee), qui exige toujours tout.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    mid_pk = trace["length"] / 2
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    start_id = next(n["id"] for n in nodes if n["pk"] == 0.0)
    end_id = next(n["id"] for n in nodes if n["pk"] == trace["length"])
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{start_id}",
        json={"type": "storage_reservoir", "name": "Res1", "data": {"fluid": "Eau potable"}},
    )
    mid = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": mid_pk, "type": "pressure_break", "name": "BC1"},
    ).json()
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{end_id}",
        json={"type": "pressure_break", "name": "BC2"},
    )

    trace_detail = client.get(f"/api/v1/projects/{session_id}/traces/{trace['id']}").json()
    max_z = max(p["z"] for p in trace_detail["elevation_profile"]["raw"])

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    seg1_id = next(s["id"] for s in segments if s["upstream_node_id"] == start_id)
    # seg2 (BC1 -> BC2) reste volontairement non valide (pas de PATCH => forced=False).
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{seg1_id}",
        json={
            "head_flow": 10.0, "upstream_water_level_max": max_z + 6.0, "upstream_water_level_min": max_z + 5.0,
            "min_pressure": 1.0, "downstream_residual_pressure": 1.0, "max_velocity": 2.0,
        },
    )

    unscoped = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert unscoped.status_code == 409  # Tr2 (BC1 -> BC2) toujours non valide

    scoped = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul",
        params={"scope_trace_id": trace["id"], "scope_start_node_id": start_id},
    )
    assert scoped.status_code == 200, scoped.text
    body = scoped.json()
    assert body["segments_updated"] == 1
    assert body["nodes_updated"] == 2

    updated_segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    seg1 = next(s for s in updated_segments if s["id"] == seg1_id)
    assert seg1["velocity"] is not None  # Tr1 bien calcule
    seg2 = next(s for s in updated_segments if s["upstream_node_id"] == mid["id"])
    assert seg2.get("velocity") is None  # Tr2 non touche


def test_calcul_scoped_to_one_troncon_still_requires_that_troncon_valid(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    start_id = nodes[0]["id"]
    response = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul",
        params={"scope_trace_id": trace["id"], "scope_start_node_id": start_id},
    )
    assert response.status_code == 409


def test_calcul_gravitaire_hydrostatic_alert_suggests_reposition_for_non_structural_reservoir(
    client, session_id, project_state, sample_kml_bytes, import_trace
):
    # Le reservoir est un noeud INTERIEUR (pas a l'extremite de la trace) — deplacable, une
    # suggestion de repositionnement doit apparaitre (consigne utilisateur : proposer de decaler
    # l'ouvrage plutot que seulement alerter). Le profil DEM synthetique de test (voir
    # services/dem.py:SyntheticDemProvider) decroit ~lineairement sur cette courte trace : un
    # troncon [0 -> pk 50] trivial (niveau tres largement suffisant) mene a un 2e troncon
    # [pk 50 -> fin] dont la cote (-7.70 m, verifiee ci-dessous) est depassee par le terrain entre
    # les PK 60 et 100 avant de repasser dessous plus loin — repositionnable.
    variant_id, trace = _import_sample(client, session_id, project_state, sample_kml_bytes, import_trace)
    nodes = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json()
    start_id = next(n["id"] for n in nodes if n["pk"] == 0.0)
    # Transparent (piquage) plutot que jonction simple : un regime determine est requis sur TOUS
    # les troncons pour lancer le calcul, y compris ce court troncon [0 -> 50] sans interet propre.
    client.patch(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{start_id}", json={"type": "tie_in", "name": ""})

    reservoir = client.post(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes",
        json={"trace_id": trace["id"], "pk": 50.0, "type": "pressure_break", "name": "BC1"},
    ).json()
    downstream_id = next(
        n["id"] for n in client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes").json() if n["pk"] == trace["length"]
    )
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{downstream_id}",
        json={"type": "pressure_break", "name": "BC2"},
    )

    segments = client.get(f"/api/v1/projects/{session_id}/variants/{variant_id}/segments").json()
    seg1_id = next(s["id"] for s in segments if s["upstream_node_id"] == start_id)
    seg2_id = next(s["id"] for s in segments if s["upstream_node_id"] == reservoir["id"])
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{seg1_id}",
        json={
            "head_flow": 10.0, "upstream_water_level_max": 200.0, "upstream_water_level_min": 195.0,
            "min_pressure": 1.0, "downstream_residual_pressure": 1.0, "max_velocity": 2.0,
        },
    )
    hydrostatic_level = -7.70
    client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/segments/{seg2_id}",
        json={
            "head_flow": 100.0,
            "upstream_water_level_max": hydrostatic_level + 0.5,
            "upstream_water_level_min": hydrostatic_level,
            "min_pressure": 5.0,
            "downstream_residual_pressure": 5.0,
            "max_velocity": 2.0,
        },
    )

    response = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul")
    assert response.status_code == 200, response.text
    body = response.json()
    assert any("hydrostatique" in a.lower() for a in body["alerts"])
    assert len(body["reposition_suggestions"]) == 1
    suggestion = body["reposition_suggestions"][0]
    assert suggestion["node_id"] == reservoir["id"]
    assert suggestion["current_pk"] == pytest.approx(50.0)
    assert suggestion["candidate_pk"] != suggestion["current_pk"]

    # Le pk candidat doit effectivement resoudre l'alerte HYDROSTATIQUE (pas forcement toute
    # alerte : le niveau -7.70 m ne laisse quasiment aucune marge de pression, d'autres alertes de
    # pression insuffisante peuvent legitimement subsister — seul le probleme hydrostatique
    # cible par la suggestion doit disparaitre).
    move_response = client.patch(
        f"/api/v1/projects/{session_id}/variants/{variant_id}/nodes/{reservoir['id']}/position",
        json={"pk": suggestion["candidate_pk"]},
    )
    assert move_response.status_code == 200, move_response.text
    recalc = client.post(f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul").json()
    assert not any("hydrostatique" in a.lower() for a in recalc["alerts"])


