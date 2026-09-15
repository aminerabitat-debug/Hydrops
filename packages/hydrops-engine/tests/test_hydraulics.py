from __future__ import annotations

import math

import pytest

from hydrops_engine.hydraulics import (
    EXCLUSION_ZONE_ALERT_MARKER,
    CatalogPipe,
    SegmentSpec,
    colebrook_white,
    kinematic_viscosity_m2s,
    max_di_mm_for_velocity,
    min_di_mm_for_velocity,
    segment_hydraulics,
    solve_gravitaire_troncon,
    solve_refoulement_troncon,
)


def test_kinematic_viscosity_decreases_with_temperature():
    assert kinematic_viscosity_m2s(20) < kinematic_viscosity_m2s(5)
    assert kinematic_viscosity_m2s(20) == pytest.approx(1.0e-6, rel=0.15)


def test_colebrook_white_turbulent_smooth_pipe_reasonable_friction_factor():
    f = colebrook_white(reynolds=100_000, relative_roughness=0.0001)
    assert 0.015 < f < 0.03


def test_colebrook_white_laminar_uses_64_over_re():
    assert colebrook_white(reynolds=1000, relative_roughness=0.001) == pytest.approx(64 / 1000)


def test_segment_hydraulics_zero_flow_gives_zero_loss():
    velocity, j = segment_hydraulics(0.0, di_mm=200, roughness_mm=0.01, viscosity_m2s=1e-6)
    assert velocity == 0.0
    assert j == 0.0


def test_segment_hydraulics_velocity_matches_area_formula():
    flow = 0.1  # m3/s
    di_mm = 300
    velocity, j = segment_hydraulics(flow, di_mm=di_mm, roughness_mm=0.01, viscosity_m2s=1e-6)
    expected_velocity = flow / (math.pi * (di_mm / 1000) ** 2 / 4)
    assert velocity == pytest.approx(expected_velocity)
    assert j > 0


def test_min_di_for_velocity_zero_without_vmax():
    assert min_di_mm_for_velocity(0.1, None) == 0.0
    assert min_di_mm_for_velocity(0.1, 0) == 0.0


def test_max_di_for_velocity_infinite_without_vmin():
    assert max_di_mm_for_velocity(0.1, None) == math.inf
    assert max_di_mm_for_velocity(0.1, 0) == math.inf


def test_max_di_for_velocity_matches_area_formula():
    flow, min_v = 0.05, 0.3
    max_di = max_di_mm_for_velocity(flow, min_v)
    area_m2 = math.pi * (max_di / 1000) ** 2 / 4
    assert flow / area_m2 == pytest.approx(min_v)


def _catalog() -> list[CatalogPipe]:
    return [
        CatalogPipe(id=1, dn=110, di_mm=99.4, material="PVC", pressure_class="PN10", pms_m=101.9, price=72.8, roughness_mm=0.01),
        CatalogPipe(id=2, dn=160, di_mm=147.6, material="PVC", pressure_class="PN10", pms_m=101.9, price=126.8, roughness_mm=0.01),
        CatalogPipe(id=3, dn=200, di_mm=184.6, material="PVC", pressure_class="PN10", pms_m=101.9, price=196.0, roughness_mm=0.01),
        CatalogPipe(id=4, dn=110, di_mm=96.8, material="PEHD", pressure_class="PN10", pms_m=101.9, price=101.9, roughness_mm=0.007),
    ]


def test_solve_gravitaire_troncon_single_segment_respects_min_pressure():
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 80.0}
    segments = [SegmentSpec(id="s1", length_m=500.0, flow_m3s=0.05, max_velocity_ms=2.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=105.0,
        upstream_level_min=103.0,
        min_pressure=5.0,
        downstream_residual_pressure=5.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert result.alerts == []
    node_b = next(n for n in result.nodes if n.node_id == "B")
    assert node_b.pressure_dynamic is not None
    assert node_b.pressure_dynamic >= 5.0 - 1e-6
    assert node_b.pressure_static_max == pytest.approx(105.0 - 80.0)
    assert node_b.pressure_static_min == pytest.approx(103.0 - 80.0)
    seg_result = result.segments[0]
    assert seg_result.head_loss_cumulative == pytest.approx(seg_result.head_loss_segment)
    # Le choix doit respecter la contrainte de vitesse (Q/A <= 2 m/s).
    area = math.pi * (seg_result.di_mm / 1000) ** 2 / 4
    assert 0.05 / area <= 2.0 + 1e-6


def test_solve_gravitaire_troncon_dn_non_increasing_downstream():
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 90.0, "C": 80.0}
    segments = [
        SegmentSpec(id="s1", length_m=500.0, flow_m3s=0.03, max_velocity_ms=3.0),
        SegmentSpec(id="s2", length_m=500.0, flow_m3s=0.03, max_velocity_ms=3.0),
    ]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B", "C"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=110.0,
        upstream_level_min=108.0,
        min_pressure=None,
        downstream_residual_pressure=None,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert result.segments[1].dn <= result.segments[0].dn


def test_solve_refoulement_troncon_derives_pump_head_from_downstream_residual():
    catalog = _catalog()
    nodes_z = {"P": 50.0, "R": 100.0}
    segments = [SegmentSpec(id="s1", length_m=2000.0, flow_m3s=0.04, max_velocity_ms=2.0)]
    result = solve_refoulement_troncon(
        node_ids_ordered=["P", "R"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=None,
        downstream_residual_pressure=20.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert result.alerts == []
    node_r = next(n for n in result.nodes if n.node_id == "R")
    assert node_r.pressure_dynamic == pytest.approx(20.0)
    assert node_r.pressure_static_max is None  # pas d'hydrostatique en refoulement (consigne utilisateur)
    node_p = next(n for n in result.nodes if n.node_id == "P")
    seg_result = result.segments[0]
    # La cote en tete = cote aval + perte de charge (parcours AMONT -> AVAL, forme close).
    assert node_p.piezo_head == pytest.approx(node_r.piezo_head + seg_result.head_loss_segment)


def test_solve_refoulement_troncon_dn_non_decreasing_towards_pump():
    catalog = _catalog()
    nodes_z = {"P": 50.0, "M": 60.0, "R": 70.0}
    segments = [
        SegmentSpec(id="s1", length_m=1000.0, flow_m3s=0.05, max_velocity_ms=3.0),
        SegmentSpec(id="s2", length_m=1000.0, flow_m3s=0.02, max_velocity_ms=3.0),
    ]
    result = solve_refoulement_troncon(
        node_ids_ordered=["P", "M", "R"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=None,
        downstream_residual_pressure=15.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    # segments[0] = P->M (le plus amont, pres de la pompe) doit avoir un DN >= segments[1] (M->R, aval).
    assert result.segments[0].dn >= result.segments[1].dn


def test_solve_refoulement_troncon_min_pressure_honored_at_intermediate_node():
    catalog = _catalog()
    # Point haut intermediaire (M a une altitude tres proche de R) : le debit/DN sont identiques
    # sur les deux segments, donc sans min_pressure la ligne piezo serait tres au-dessus de M —
    # min_pressure doit neanmoins etre respectee la aussi, pas seulement au point aval R.
    nodes_z = {"P": 50.0, "M": 95.0, "R": 70.0}
    segments = [
        SegmentSpec(id="s1", length_m=500.0, flow_m3s=0.03, max_velocity_ms=3.0),
        SegmentSpec(id="s2", length_m=500.0, flow_m3s=0.03, max_velocity_ms=3.0),
    ]
    result = solve_refoulement_troncon(
        node_ids_ordered=["P", "M", "R"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=8.0,
        downstream_residual_pressure=15.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    node_m = next(n for n in result.nodes if n.node_id == "M")
    node_r = next(n for n in result.nodes if n.node_id == "R")
    assert node_m.pressure_dynamic >= 8.0 - 1e-6
    assert node_r.pressure_dynamic >= 15.0 - 1e-6


def test_solve_refoulement_troncon_pms_exceeded_raises_alert_not_exception():
    # PMS tres bas sur toutes les lignes du catalogue + residuelle aval elevee -> la pression de
    # service depasse forcement le PMS retenu (aucune conduite ne peut le respecter) : une alerte,
    # jamais une exception, et le calcul retourne quand meme un resultat exploitable.
    catalog = [
        CatalogPipe(id=1, dn=200, di_mm=184.6, material="PVC", pressure_class="PN2", pms_m=5.0, price=196.0, roughness_mm=0.01),
    ]
    nodes_z = {"P": 50.0, "R": 100.0}
    segments = [SegmentSpec(id="s1", length_m=2000.0, flow_m3s=0.04, max_velocity_ms=2.0)]
    result = solve_refoulement_troncon(
        node_ids_ordered=["P", "R"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=None,
        downstream_residual_pressure=80.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert any("PMS" in a for a in result.alerts)
    assert len(result.segments) == 1


def test_solve_gravitaire_troncon_insufficient_reservoir_level_raises_alert():
    catalog = _catalog()
    # Residuelle aval elevee mais reservoir tres bas (a peine au-dessus du terrain aval) : meme
    # sans aucune perte de charge, le niveau disponible ne peut pas suffire.
    nodes_z = {"A": 100.0, "B": 80.0}
    segments = [SegmentSpec(id="s1", length_m=200.0, flow_m3s=0.01, max_velocity_ms=2.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=101.0,
        upstream_level_min=100.5,
        min_pressure=None,
        downstream_residual_pressure=50.0,  # exige cote_B >= 130, hors de portee d'un reservoir a 100.5
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert any("réservoir" in a.lower() for a in result.alerts)


def test_solve_gravitaire_troncon_infeasible_pressure_raises_alert_not_exception():
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 99.0}
    segments = [SegmentSpec(id="s1", length_m=5000.0, flow_m3s=0.08, max_velocity_ms=2.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=101.0,
        upstream_level_min=100.5,
        min_pressure=50.0,  # volontairement irrealiste pour forcer l'infaisabilite
        downstream_residual_pressure=None,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert len(result.alerts) >= 1
    assert len(result.segments) == 1


def test_solve_gravitaire_troncon_detects_intermediate_terrain_high_point():
    # Un troncon peut n'avoir que 2 noeuds reels (ses extremites) mais couvrir un terrain
    # accidente entre les deux : verifier la pression aux seuls noeuds ne suffit pas — un point
    # haut intermediaire (jamais materialise par un noeud) peut passer sous la ligne piezometrique
    # sans qu'aucune des deux extremites ne le detecte (cas signale par l'utilisateur).
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 95.0}
    segments = [SegmentSpec(id="s1", length_m=1000.0, flow_m3s=0.001, max_velocity_ms=2.0)]
    node_pk = {"A": 0.0, "B": 1000.0}
    # Un "point haut" a mi-troncon (PK 500, z=108), bien au-dessus des deux extremites (100/95) et
    # tres proche du niveau du reservoir (112) : la ligne piezometrique (quasi plate, faible debit)
    # y laisse une pression tres inferieure aux 5 m minimum exiges, alors que A et B sont corrects.
    terrain_samples = [(0.0, 100.0), (200.0, 96.0), (500.0, 108.0), (800.0, 94.0), (1000.0, 95.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=115.0,
        upstream_level_min=112.0,
        min_pressure=5.0,
        downstream_residual_pressure=None,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk=node_pk,
        terrain_samples=terrain_samples,
    )
    node_b = next(n for n in result.nodes if n.node_id == "B")
    # Les deux extremites respectent la pression minimale...
    assert node_b.pressure_dynamic >= 5.0 - 1e-6
    # ...mais le point haut intermediaire (PK 500, z=108) doit etre detecte malgre tout.
    assert any("terrain" in a.lower() and "500" in a for a in result.alerts)


def test_solve_gravitaire_troncon_terrain_check_silent_when_profile_clears_it():
    # Meme troncon, mais un terrain qui reste sous la ligne piezometrique partout : aucune alerte
    # de terrain ne doit apparaitre (pas de faux positif).
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 95.0}
    segments = [SegmentSpec(id="s1", length_m=1000.0, flow_m3s=0.001, max_velocity_ms=2.0)]
    node_pk = {"A": 0.0, "B": 1000.0}
    terrain_samples = [(0.0, 100.0), (200.0, 96.0), (500.0, 97.0), (800.0, 94.0), (1000.0, 95.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=115.0,
        upstream_level_min=112.0,
        min_pressure=5.0,
        downstream_residual_pressure=None,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk=node_pk,
        terrain_samples=terrain_samples,
    )
    assert not any("terrain" in a.lower() for a in result.alerts)


def test_solve_refoulement_troncon_raises_h0_to_cover_intermediate_terrain_high_point():
    catalog = _catalog()
    nodes_z = {"P": 50.0, "R": 60.0}
    segments = [SegmentSpec(id="s1", length_m=1000.0, flow_m3s=0.001, max_velocity_ms=2.0)]
    node_pk = {"P": 0.0, "R": 1000.0}
    # Point haut intermediaire (PK 500, z=72) : ni P ni R ne l'exigent directement (tous deux
    # calcules pour respecter leurs propres exigences), donc sans prise en compte du terrain la
    # ligne piezometrique passerait sous ce point. En refoulement, pas d'alerte : H0 doit etre
    # augmentee jusqu'a ce que ce point soit lui aussi couvert.
    terrain_samples = [(0.0, 50.0), (500.0, 72.0), (1000.0, 60.0)]
    result = solve_refoulement_troncon(
        node_ids_ordered=["P", "R"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=8.0,
        downstream_residual_pressure=15.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk=node_pk,
        terrain_samples=terrain_samples,
    )
    assert not any("terrain" in a.lower() for a in result.alerts)

    node_p = next(n for n in result.nodes if n.node_id == "P")
    node_r = next(n for n in result.nodes if n.node_id == "R")
    # H0 a ete pousse au-dela de ce que R exigeait seul (15.0 m de residuel) pour couvrir le
    # point haut intermediaire.
    assert node_r.pressure_dynamic > 15.0

    # La pression interpolee au point haut (pk=500, z=72) respecte tout juste min_pressure.
    t = 500.0 / 1000.0
    cote_500 = node_p.piezo_head + t * (node_r.piezo_head - node_p.piezo_head)
    assert (cote_500 - 72.0) == pytest.approx(8.0)


def test_solve_gravitaire_troncon_hydrostatic_precheck_skips_calc_when_terrain_submerges_reservoir():
    # Le terrain (piquet a PK 5000, z=101.0) atteint deja la cote hydrostatique du reservoir amont
    # (niveau min = 100.0) : aucun dimensionnement de conduite ne peut jamais y faire passer un
    # ecoulement gravitaire, donc pas de reconstruction detaillee — juste l'alerte, et les noeuds
    # explicitement remis a "non calcule" (consigne utilisateur).
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 60.0}
    segments = [SegmentSpec(id="s1", length_m=10000.0, flow_m3s=0.01, max_velocity_ms=2.0)]
    node_pk = {"A": 0.0, "B": 10000.0}
    terrain_samples = [(0.0, 100.0), (5000.0, 101.0), (10000.0, 60.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.5,
        upstream_level_min=100.0,
        min_pressure=5.0,
        downstream_residual_pressure=10.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk=node_pk,
        terrain_samples=terrain_samples,
    )
    assert result.segments == []
    assert all(n.piezo_head is None and n.pressure_dynamic is None for n in result.nodes)
    assert any("hydrostatique" in a.lower() and "5000" in a for a in result.alerts)


def test_solve_gravitaire_troncon_hydrostatic_precheck_silent_when_profile_clears_it():
    catalog = _catalog()
    nodes_z = {"A": 95.0, "B": 60.0}
    segments = [SegmentSpec(id="s1", length_m=1000.0, flow_m3s=0.001, max_velocity_ms=2.0)]
    node_pk = {"A": 0.0, "B": 1000.0}
    terrain_samples = [(0.0, 95.0), (500.0, 90.0), (1000.0, 60.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.5,
        upstream_level_min=100.0,
        min_pressure=5.0,
        downstream_residual_pressure=10.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk=node_pk,
        terrain_samples=terrain_samples,
    )
    assert not any("hydrostatique" in a.lower() for a in result.alerts)
    assert len(result.segments) == 1


def test_solve_gravitaire_troncon_hydrostatic_precheck_disabled_when_level_not_configured():
    # upstream_level_min=None (niveau pas encore renseigne dans "Modifier le tronçon") : le
    # pre-check doit rester desactive, meme si le terrain depasse largement 0 (comportement
    # actuel inchange, pas de faux positif).
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 60.0}
    segments = [SegmentSpec(id="s1", length_m=10000.0, flow_m3s=0.01, max_velocity_ms=2.0)]
    node_pk = {"A": 0.0, "B": 10000.0}
    terrain_samples = [(0.0, 100.0), (5000.0, 101.0), (10000.0, 60.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.5,
        upstream_level_min=None,
        min_pressure=None,
        downstream_residual_pressure=None,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk=node_pk,
        terrain_samples=terrain_samples,
    )
    assert not any("hydrostatique" in a.lower() for a in result.alerts)
    assert len(result.segments) == 1


def test_solve_gravitaire_troncon_bumps_upstream_dn_to_resolve_pressure_violation():
    # Avec le DN le moins cher (110) sur les deux segments, le noeud intermediaire M viole la
    # pression minimale (-16.5 m obtenus pour 20.0 m requis) alors que B, plus en aval mais sur un
    # denivele plus favorable, la respecte deja — verifie via _gravitaire_pass dans le
    # developpement de ce test. Un DN plus gros sur le segment AMONT de M (A-M) doit resoudre le
    # deficit (consigne utilisateur : "augmenter le diametre a l'amont du point en question").
    catalog = _catalog()
    nodes_z = {"A": 100.0, "M": 50.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=6000.0, flow_m3s=0.008, max_velocity_ms=2.0),
        SegmentSpec(id="s2", length_m=1000.0, flow_m3s=0.008, max_velocity_ms=2.0),
    ]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.5,
        upstream_level_min=100.0,
        min_pressure=20.0,
        downstream_residual_pressure=0.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert not any("pression insuffisante" in a.lower() for a in result.alerts)
    node_m = next(n for n in result.nodes if n.node_id == "M")
    assert node_m.pressure_dynamic >= 20.0 - 1e-6
    seg_s1 = next(s for s in result.segments if s.id == "s1")
    assert seg_s1.dn > 110  # DN le moins cher initialement choisi, avant augmentation


def test_solve_gravitaire_troncon_bump_stops_at_min_velocity_ceiling():
    # Meme scenario que le bump ci-dessus (DN110 -> insuffisant, DN160 dispo et resoudrait le
    # deficit), mais avec une vitesse min (Preferences, consigne utilisateur) plus haute que la
    # vitesse qu'aurait le segment une fois passe a DN160 (~0.47 m/s) — l'augmentation doit
    # s'arreter la (aucune conduite ne respecte a la fois vitesse min et le palier superieur),
    # l'alerte "pression insuffisante" doit donc persister plutot que d'ignorer la vitesse min.
    catalog = _catalog()
    nodes_z = {"A": 100.0, "M": 50.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=6000.0, flow_m3s=0.008, max_velocity_ms=2.0, min_velocity_ms=0.6),
        SegmentSpec(id="s2", length_m=1000.0, flow_m3s=0.008, max_velocity_ms=2.0),
    ]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.5,
        upstream_level_min=100.0,
        min_pressure=20.0,
        downstream_residual_pressure=0.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert any("pression insuffisante" in a.lower() for a in result.alerts)
    seg_s1 = next(s for s in result.segments if s.id == "s1")
    assert seg_s1.dn == 110  # le palier 160 existe mais violerait la vitesse min, donc refuse


def test_solve_gravitaire_troncon_pressure_violation_persists_when_no_bigger_dn_available():
    # Meme scenario que ci-dessus, mais un catalogue limite au seul DN110 (aucun DN plus gros
    # disponible) : la tentative d'augmentation ne peut pas aboutir, l'alerte doit persister sans
    # boucle infinie ni exception.
    catalog = [
        CatalogPipe(id=1, dn=110, di_mm=99.4, material="PVC", pressure_class="PN10", pms_m=101.9, price=72.8, roughness_mm=0.01),
    ]
    nodes_z = {"A": 100.0, "M": 50.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=6000.0, flow_m3s=0.008, max_velocity_ms=2.0),
        SegmentSpec(id="s2", length_m=1000.0, flow_m3s=0.008, max_velocity_ms=2.0),
    ]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.5,
        upstream_level_min=100.0,
        min_pressure=20.0,
        downstream_residual_pressure=0.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert any("pression insuffisante" in a.lower() for a in result.alerts)
    seg_s1 = next(s for s in result.segments if s.id == "s1")
    assert seg_s1.dn == 110


def test_solve_gravitaire_troncon_forced_dn_never_bumped_alert_persists():
    # Meme scenario que test_..._bumps_upstream_dn_to_resolve_pressure_violation, mais s1 a un
    # DN force (consigne utilisateur : "fixer des contraintes Materiau et DN... le calcul doit se
    # faire meme si certaines contraintes de pression... sont violees") — l'augmentation
    # iterative ne doit JAMAIS toucher un segment force : le DN reste 110, la pression insuffisante
    # au noeud M persiste comme alerte informative, mais le calcul aboutit quand meme (segments et
    # noeuds bien renseignes, pas un echec bloquant).
    catalog = _catalog()
    nodes_z = {"A": 100.0, "M": 50.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=6000.0, flow_m3s=0.008, max_velocity_ms=2.0, forced_material="PVC", forced_dn=110),
        SegmentSpec(id="s2", length_m=1000.0, flow_m3s=0.008, max_velocity_ms=2.0),
    ]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.5,
        upstream_level_min=100.0,
        min_pressure=20.0,
        downstream_residual_pressure=0.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert any("pression insuffisante" in a.lower() for a in result.alerts)
    seg_s1 = next(s for s in result.segments if s.id == "s1")
    assert seg_s1.dn == 110
    assert seg_s1.material == "PVC"
    node_m = next(n for n in result.nodes if n.node_id == "M")
    assert node_m.pressure_dynamic is not None  # calcul quand meme abouti, pas de reset


def test_solve_gravitaire_troncon_forced_dn_alerts_on_velocity_violation():
    # DN force bien plus gros que necessaire pour ce debit -> vitesse tres en dessous de la
    # vitesse min demandee : une alerte dediee doit le signaler, sans jamais changer le DN (a la
    # difference du plafond de vitesse min qui s'applique seulement au dimensionnement automatique).
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 0.0}
    segments = [
        SegmentSpec(
            id="s1", length_m=1000.0, flow_m3s=0.001, min_velocity_ms=1.0,
            forced_material="PVC", forced_dn=200,
        ),
    ]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=105.0,
        upstream_level_min=104.0,
        min_pressure=None,
        downstream_residual_pressure=None,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert any("inférieure à la vitesse min" in a for a in result.alerts)
    seg_s1 = result.segments[0]
    assert seg_s1.dn == 200
    assert seg_s1.material == "PVC"


def test_solve_gravitaire_troncon_forced_dn_unknown_combination_alerts_and_falls_back():
    # Materiau/DN force absent du catalogue (ne devrait pas arriver, ecarte a la saisie cote API —
    # cf. services/catalog.py:material_dn_exists) : ne doit jamais lever d'exception, une alerte
    # explicite et un repli sur une conduite quelconque suffisent.
    catalog = _catalog()  # ne contient aucun DN 999
    nodes_z = {"A": 100.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=1000.0, flow_m3s=0.001, forced_material="PVC", forced_dn=999),
    ]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=105.0,
        upstream_level_min=104.0,
        min_pressure=None,
        downstream_residual_pressure=None,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert any("aucune conduite active" in a.lower() for a in result.alerts)
    assert len(result.segments) == 1


def test_solve_gravitaire_troncon_forced_dn_only_autopicks_cheapest_material():
    # Contrainte PARTIELLE (consigne utilisateur, contraintes par plage de PK) : DN force SEUL,
    # sans materiau — le materiau le moins cher disponible a ce DN est choisi automatiquement (PVC
    # DN110 @ 72.8 < PEHD DN110 @ 101.9 dans _catalog()), sans jamais figer le materiau.
    catalog = _catalog()
    nodes_z = {"A": 40.0, "B": 0.0}
    segments = [SegmentSpec(id="s1", length_m=500.0, flow_m3s=0.001, forced_dn=110)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"], node_ground_z=nodes_z, segments_ordered=segments,
        upstream_level_max=50.0, upstream_level_min=49.0, min_pressure=None,
        downstream_residual_pressure=None, catalog=catalog, singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert not result.alerts
    seg_s1 = result.segments[0]
    assert seg_s1.dn == 110
    assert seg_s1.material == "PVC"


def test_solve_gravitaire_troncon_forced_material_only_autosizes_dn():
    # Materiau force SEUL, sans DN — le DN le moins cher respectant la vitesse max est choisi
    # automatiquement, restreint a ce materiau (jamais PEHD, meme si moins cher a un autre DN).
    catalog = _catalog()
    nodes_z = {"A": 40.0, "B": 0.0}
    segments = [SegmentSpec(id="s1", length_m=500.0, flow_m3s=0.001, max_velocity_ms=2.0, forced_material="PVC")]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"], node_ground_z=nodes_z, segments_ordered=segments,
        upstream_level_max=50.0, upstream_level_min=49.0, min_pressure=None,
        downstream_residual_pressure=None, catalog=catalog, singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert not result.alerts
    seg_s1 = result.segments[0]
    assert seg_s1.material == "PVC"
    assert seg_s1.dn == 110  # le plus petit/moins cher PVC qui respecte la vitesse max


def test_solve_gravitaire_troncon_forced_pressure_class_only_autosizes_material_and_dn():
    # Classe de pression forcee SEULE (ex. homogeneisation, consigne utilisateur) — materiau ET DN
    # restent choisis automatiquement, mais seulement parmi les conduites de cette classe.
    catalog = [
        CatalogPipe(id=1, dn=110, di_mm=99.4, material="PVC", pressure_class="PN6", pms_m=61.2, price=50.0, roughness_mm=0.01),
        CatalogPipe(id=2, dn=110, di_mm=99.4, material="PVC", pressure_class="PN16", pms_m=163.1, price=90.0, roughness_mm=0.01),
    ]
    nodes_z = {"A": 100.0, "B": 0.0}
    segments = [SegmentSpec(id="s1", length_m=500.0, flow_m3s=0.001, forced_pressure_class="PN16")]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"], node_ground_z=nodes_z, segments_ordered=segments,
        upstream_level_max=105.0, upstream_level_min=104.0, min_pressure=None,
        downstream_residual_pressure=None, catalog=catalog, singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    assert not result.alerts
    seg_s1 = result.segments[0]
    assert seg_s1.pressure_class == "PN16"
    assert seg_s1.material == "PVC"
    assert seg_s1.dn == 110


def test_solve_refoulement_troncon_forced_dn_upgrades_class_to_cover_pressure():
    # DN force dont la classe la moins chere (PN6) est insuffisante face a la pression resultante —
    # une classe superieure existe (PN16, meme DN/materiau) et doit etre retenue automatiquement
    # (consigne utilisateur : "tu ne peux pas prevoir PN10 lorsque la pression est 12 bar"), sans
    # jamais changer le DN force lui-meme. Plus d'alerte, la classe retenue couvre la pression.
    catalog = [
        CatalogPipe(id=1, dn=110, di_mm=99.4, material="PVC", pressure_class="PN6", pms_m=61.2, price=50.0, roughness_mm=0.01),
        CatalogPipe(id=2, dn=110, di_mm=99.4, material="PVC", pressure_class="PN16", pms_m=163.1, price=90.0, roughness_mm=0.01),
    ]
    nodes_z = {"A": 0.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=100.0, flow_m3s=0.01, forced_material="PVC", forced_dn=110),
    ]
    result = solve_refoulement_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=None,
        downstream_residual_pressure=100.0,  # exige H0 tres eleve -> pression statique > PN6 (61.2 m)
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    seg_s1 = result.segments[0]
    assert seg_s1.dn == 110
    assert seg_s1.pressure_class == "PN16"
    assert not any("dépasse le pms" in a.lower() or "à revoir" in a.lower() for a in result.alerts)


def test_solve_refoulement_troncon_forced_dn_alerts_when_no_class_covers_pressure():
    # Meme scenario, mais aucune classe disponible (seule PN6) ne couvre la pression requise —
    # l'alerte doit persister (dernier recours), le DN force reste inchange.
    catalog = [
        CatalogPipe(id=1, dn=110, di_mm=99.4, material="PVC", pressure_class="PN6", pms_m=61.2, price=50.0, roughness_mm=0.01),
    ]
    nodes_z = {"A": 0.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=100.0, flow_m3s=0.01, forced_material="PVC", forced_dn=110),
    ]
    result = solve_refoulement_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=None,
        downstream_residual_pressure=100.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    seg_s1 = result.segments[0]
    assert seg_s1.dn == 110
    assert seg_s1.pressure_class == "PN6"
    assert any("dépasse le pms" in a.lower() for a in result.alerts)


def test_solve_refoulement_troncon_auto_dimensioning_upgrades_class_to_cover_pressure():
    # Meme principe SANS DN force (dimensionnement automatique) : le premier passage ignore la
    # pression (choisit la classe la moins chere respectant la vitesse), puis doit relever son
    # plancher PMS et re-choisir une classe adequate une fois la pression dynamique connue.
    catalog = [
        CatalogPipe(id=1, dn=110, di_mm=99.4, material="PVC", pressure_class="PN6", pms_m=61.2, price=50.0, roughness_mm=0.01),
        CatalogPipe(id=2, dn=110, di_mm=97.4, material="PVC", pressure_class="PN16", pms_m=163.1, price=90.0, roughness_mm=0.01),
    ]
    nodes_z = {"A": 0.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=100.0, flow_m3s=0.005, max_velocity_ms=2.0),
    ]
    result = solve_refoulement_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=None,
        downstream_residual_pressure=100.0,  # pression statique en A > PN6 (61.2 m)
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
    )
    seg_s1 = result.segments[0]
    assert seg_s1.pressure_class == "PN16"
    assert not any("dépasse le pms" in a.lower() for a in result.alerts)


def test_solve_gravitaire_troncon_min_pressure_exclusion_zone_is_informative_not_blocking():
    # M est a la meme altitude que le reservoir (100 m) et tout pres de lui (pk 300 sur 6300 m,
    # soit ~4.8% du tronçon) — sa pression "naturelle" y est structurellement faible (quasi aucune
    # perte de charge consommee, mais deja a l'altitude du reservoir), independamment du DN choisi
    # (meme phenomene que pres d'un reservoir en pratique). Sans zone d'exclusion, ce deficit
    # bloquerait le calcul (alerte "pression insuffisante", cf. tests ci-dessus). Avec une zone
    # d'exclusion de 10% (Preferences, consigne utilisateur), M en est exempte : seule une alerte
    # informative au prefixe reconnu doit apparaitre, jamais la version bloquante.
    catalog = _catalog()
    nodes_z = {"A": 100.0, "M": 100.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=300.0, flow_m3s=0.008, max_velocity_ms=2.0),
        SegmentSpec(id="s2", length_m=6000.0, flow_m3s=0.008, max_velocity_ms=2.0),
    ]
    kwargs = dict(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=101.0,
        upstream_level_min=100.0,
        min_pressure=20.0,
        downstream_residual_pressure=0.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk={"A": 0.0, "M": 300.0, "B": 6300.0},
    )

    without_exclusion = solve_gravitaire_troncon(**kwargs)
    assert any("pression insuffisante" in a.lower() for a in without_exclusion.alerts)
    assert not any(EXCLUSION_ZONE_ALERT_MARKER in a for a in without_exclusion.alerts)

    with_exclusion = solve_gravitaire_troncon(**kwargs, min_pressure_exclusion_m=630.0)  # 10% de 6300 m
    assert not any("pression insuffisante au" in a.lower() for a in with_exclusion.alerts)
    assert any(EXCLUSION_ZONE_ALERT_MARKER in a for a in with_exclusion.alerts)
    node_m = next(n for n in with_exclusion.nodes if n.node_id == "M")
    assert node_m.pressure_dynamic is not None and node_m.pressure_dynamic < 20.0  # calcule quand meme


def test_solve_gravitaire_troncon_downstream_residual_still_applies_within_exclusion_zone():
    # La residuelle aval (au dernier noeud) doit toujours s'appliquer, meme si ce noeud tombe dans
    # la zone d'exclusion — seule `min_pressure` en est desactivable (consigne utilisateur). La
    # translation peut ajouter un surplus (offset >= 0) : on verifie donc "au moins" la residuelle,
    # jamais une egalite stricte (une marge positive ne doit jamais compter comme une violation).
    catalog = _catalog()
    nodes_z = {"A": 100.0, "B": 95.0}
    segments = [SegmentSpec(id="s1", length_m=50.0, flow_m3s=0.001, max_velocity_ms=2.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=110.0,
        upstream_level_min=108.0,
        min_pressure=None,
        downstream_residual_pressure=5.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk={"A": 0.0, "B": 50.0},
        min_pressure_exclusion_m=50.0,  # exclut tout le tronçon
    )
    assert result.alerts == []
    node_b = next(n for n in result.nodes if n.node_id == "B")
    assert node_b.pressure_dynamic >= 5.0 - 1e-6


def test_solve_refoulement_troncon_min_pressure_exclusion_zone_is_informative_not_blocking():
    # Meme principe qu'en gravitaire, mais H0 ne doit pas non plus etre gonfle pour satisfaire le
    # noeud exclu — la comparaison avec/sans exclusion doit montrer un H0 (donc une piezo) plus
    # bas une fois M exempte.
    catalog = _catalog()
    nodes_z = {"A": 0.0, "M": 90.0, "B": 0.0}
    segments = [
        SegmentSpec(id="s1", length_m=100.0, flow_m3s=0.008, max_velocity_ms=2.0),
        SegmentSpec(id="s2", length_m=5000.0, flow_m3s=0.008, max_velocity_ms=2.0),
    ]
    kwargs = dict(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=20.0,
        downstream_residual_pressure=0.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        node_pk={"A": 0.0, "M": 100.0, "B": 5100.0},
    )
    without_exclusion = solve_refoulement_troncon(**kwargs)
    with_exclusion = solve_refoulement_troncon(**kwargs, min_pressure_exclusion_m=255.0)  # 5% de 5100 m
    assert any(EXCLUSION_ZONE_ALERT_MARKER in a for a in with_exclusion.alerts)
    node_a_without = next(n for n in without_exclusion.nodes if n.node_id == "A")
    node_a_with = next(n for n in with_exclusion.nodes if n.node_id == "A")
    assert node_a_with.piezo_head < node_a_without.piezo_head - 1e-6


def test_solve_gravitaire_troncon_telescopes_smaller_dn_toward_aval_when_budget_allows():
    # Procedure validee avec l'utilisateur : une fois une solution SANS alerte obtenue (le DN le
    # moins cher respectant vitesse/PMS), on tente de la reduire par paliers catalogue successifs
    # en partant du segment le plus AVAL et en remontant — ici, le plancher de pression (bump-loop)
    # remonte d'abord les DEUX segments a DN110 (le DN90 initial, moins cher, ne tient pas la
    # pression residuelle sur les 430 m cumules) ; l'optimisation telescopique doit ensuite
    # reussir a redescendre le segment aval (tail, 30 m) a DN90 tout en gardant le segment amont
    # (main, 400 m) a DN110 — la reduction inverse (main a 90, tail a 110) violerait la pression.
    catalog = [
        CatalogPipe(id=1, dn=90, di_mm=80.0, material="PVC", pressure_class="PN10", pms_m=101.9, price=50.0, roughness_mm=0.01),
        CatalogPipe(id=2, dn=110, di_mm=99.4, material="PVC", pressure_class="PN10", pms_m=101.9, price=72.8, roughness_mm=0.01),
        CatalogPipe(id=3, dn=160, di_mm=147.6, material="PVC", pressure_class="PN10", pms_m=101.9, price=126.8, roughness_mm=0.01),
    ]
    nodes_z = {"A": 0.0, "M": 0.0, "B": 0.0}
    segments = [
        SegmentSpec(id="main", length_m=400.0, flow_m3s=0.03, max_velocity_ms=6.0),
        SegmentSpec(id="tail", length_m=30.0, flow_m3s=0.03, max_velocity_ms=6.0),
    ]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.0,
        upstream_level_min=100.0,
        min_pressure=None,
        downstream_residual_pressure=40.0,
        catalog=catalog,
        singular_loss_markup_pct=0.0,
        fluid_temperature_c=20.0,
    )
    assert result.alerts == []
    main_result = next(r for r in result.segments if r.id == "main")
    tail_result = next(r for r in result.segments if r.id == "tail")
    assert main_result.dn == 110
    assert tail_result.dn == 90
    assert main_result.dn >= tail_result.dn
    node_b = next(n for n in result.nodes if n.node_id == "B")
    assert node_b.pressure_dynamic >= 40.0 - 1e-6


def test_solve_gravitaire_troncon_does_not_telescope_when_no_pressure_margin():
    # Meme catalogue/geometrie, mais avec une residuelle qui ne laisse aucune marge : le DN110
    # uniforme tient tout juste (aucune alerte), et la reduction du segment aval a DN90 doit etre
    # refusee (elle ferait chuter la pression sous l'exigence) — pas de regression du comportement
    # existant quand il n'y a rien a optimiser.
    catalog = [
        CatalogPipe(id=1, dn=90, di_mm=80.0, material="PVC", pressure_class="PN10", pms_m=101.9, price=50.0, roughness_mm=0.01),
        CatalogPipe(id=2, dn=110, di_mm=99.4, material="PVC", pressure_class="PN10", pms_m=101.9, price=72.8, roughness_mm=0.01),
    ]
    nodes_z = {"A": 0.0, "M": 0.0, "B": 0.0}
    segments = [
        SegmentSpec(id="main", length_m=400.0, flow_m3s=0.03, max_velocity_ms=6.0),
        SegmentSpec(id="tail", length_m=30.0, flow_m3s=0.03, max_velocity_ms=6.0),
    ]
    # Perte a DN110 uniforme ~= 49.28 m (0.114597 * 430) -> residuelle tout juste tenue avec ~50.7 m
    # de marge disponible (upstream_level_min - residuelle = 100 - 49.3), sans marge pour DN90 sur
    # le segment aval (perte tail seule seul passerait de ~3.4 m a ~10.1 m, soit +6.7 m -> deficit).
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.0,
        upstream_level_min=100.0,
        min_pressure=None,
        downstream_residual_pressure=50.7,
        catalog=catalog,
        singular_loss_markup_pct=0.0,
        fluid_temperature_c=20.0,
    )
    assert result.alerts == []
    main_result = next(r for r in result.segments if r.id == "main")
    tail_result = next(r for r in result.segments if r.id == "tail")
    assert main_result.dn == 110
    assert tail_result.dn == 110


def test_solve_gravitaire_troncon_forced_downstream_segment_does_not_shrink_free_upstream_dn():
    # Regression (retour utilisateur : "en principe la ligne piezo et les DN ne devraient pas
    # changer" apres homogeneisation d'une zone AVAL deja optimale) : forcer le segment "tail" a
    # son DN naturel (homogeneisation d'une plage deja au bon DN, un no-op physique en soi) ne doit
    # PAS faire retrecir le segment LIBRE "main" en amont. Avant le correctif, le forcage etablit un
    # plancher `dn_floor`=90 des la toute PREMIERE passe de base (avant meme toute reduction
    # telescopique) ; `_candidates` choisit alors le DN le moins cher (90) pour "main" — le point de
    # terrain a pk=200 (entre A et M, jamais lui-meme un piquet) manque alors la pression requise,
    # mais seule une interpolation lineaire entre piquets (`_check_terrain_pressure`) peut le
    # detecter : le piquet M lui-meme (son propre `required_by_node`) reste hors de cause ici (son
    # altitude est volontairement tres basse pour l'isoler de ce cas), donc SEUL un vrai controle
    # terrain dans la boucle de base peut reagir. Avant le correctif, ce controle n'existait que
    # dans la toute derniere verification (`_check_terrain_pressure` en fin de fonction), bien trop
    # tard pour influer sur le choix de DN. Le correctif etend le bouclage d'augmentation iterative
    # (bump-loop) pour aussi reagir a une violation terrain, en remontant au premier segment LIBRE
    # en amont d'elle (ici "main") puisque le segment force au point de violation ne peut, par
    # construction, jamais etre augmente.
    catalog = [
        CatalogPipe(id=1, dn=90, di_mm=80.0, material="PVC", pressure_class="PN10", pms_m=500.0, price=50.0, roughness_mm=0.01),
        CatalogPipe(id=2, dn=110, di_mm=99.4, material="PVC", pressure_class="PN10", pms_m=500.0, price=72.8, roughness_mm=0.01),
        CatalogPipe(id=3, dn=160, di_mm=147.6, material="PVC", pressure_class="PN10", pms_m=500.0, price=126.8, roughness_mm=0.01),
    ]
    # M et B sont volontairement tres bas (-100 m) : leur propre exigence de pression
    # (`required_by_node`, deja verifiee AVANT ce correctif) reste alors toujours tres confortable
    # quel que soit le DN de "main", isolant la violation testee au seul point de TERRAIN
    # intermediaire (pk=200) — sinon le bump-loop existant la corrigerait deja "par coincidence" via
    # le noeud M, sans jamais passer par le nouveau chemin teste ici.
    nodes_z = {"A": 0.0, "M": -100.0, "B": -100.0}
    node_pk = {"A": 0.0, "M": 400.0, "B": 430.0}
    segments = [
        SegmentSpec(id="main", length_m=400.0, flow_m3s=0.03, max_velocity_ms=6.0),
        SegmentSpec(id="tail", length_m=30.0, flow_m3s=0.03, max_velocity_ms=6.0, forced_material="PVC", forced_dn=90),
    ]
    # Terrain (z=0) au milieu de "main" (pk 200, entre A et M) : avec main=DN90, la cote piezo
    # interpolee y tombe a ~82.8 m (< 90 m requis) ; avec main=DN110, elle remonte a ~127.1 m (marge
    # confortable) — verifie numeriquement ci-dessous par l'assertion finale sur le DN retenu et
    # l'absence d'alerte.
    terrain_samples = [(200.0, 0.0)]
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=150.0,
        upstream_level_min=150.0,
        min_pressure=90.0,
        downstream_residual_pressure=0.0,
        catalog=catalog,
        singular_loss_markup_pct=0.0,
        fluid_temperature_c=20.0,
        node_pk=node_pk,
        terrain_samples=terrain_samples,
    )
    assert result.alerts == []
    main_result = next(r for r in result.segments if r.id == "main")
    tail_result = next(r for r in result.segments if r.id == "tail")
    assert main_result.dn == 110
    assert tail_result.dn == 90


def test_solve_gravitaire_troncon_on_progress_reaches_done_equals_total_and_is_monotonic():
    # Consigne utilisateur : barre de progression a pourcentage reel pour le calcul (remplace le
    # pas d'echantillonnage hydraulique fixe) — reprend le scenario de telescopage existant
    # (2 segments, boucle de reduction reellement exercee) pour verifier que le callback est
    # appele au moins une fois, jamais decroissant, et se termine toujours a done == total.
    catalog = [
        CatalogPipe(id=1, dn=90, di_mm=80.0, material="PVC", pressure_class="PN10", pms_m=101.9, price=50.0, roughness_mm=0.01),
        CatalogPipe(id=2, dn=110, di_mm=99.4, material="PVC", pressure_class="PN10", pms_m=101.9, price=72.8, roughness_mm=0.01),
        CatalogPipe(id=3, dn=160, di_mm=147.6, material="PVC", pressure_class="PN10", pms_m=101.9, price=126.8, roughness_mm=0.01),
    ]
    nodes_z = {"A": 0.0, "M": 0.0, "B": 0.0}
    segments = [
        SegmentSpec(id="main", length_m=400.0, flow_m3s=0.03, max_velocity_ms=6.0),
        SegmentSpec(id="tail", length_m=30.0, flow_m3s=0.03, max_velocity_ms=6.0),
    ]
    calls: list[tuple[int, int]] = []
    result = solve_gravitaire_troncon(
        node_ids_ordered=["A", "M", "B"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        upstream_level_max=100.0,
        upstream_level_min=100.0,
        min_pressure=None,
        downstream_residual_pressure=40.0,
        catalog=catalog,
        singular_loss_markup_pct=0.0,
        fluid_temperature_c=20.0,
        on_progress=lambda done, total: calls.append((done, total)),
    )
    assert result.alerts == []
    assert calls  # au moins un appel
    assert all(total == calls[0][1] for _, total in calls)  # total stable sur tout l'appel
    assert calls[0][1] > 0
    assert all(a[0] <= b[0] for a, b in zip(calls, calls[1:]))  # jamais decroissant
    assert calls[-1][0] == calls[-1][1]  # termine toujours a done == total


def test_solve_gravitaire_troncon_on_progress_does_not_change_result():
    # Le callback ne doit rien muter — memes segments/alertes avec ou sans lui.
    catalog = [
        CatalogPipe(id=1, dn=90, di_mm=80.0, material="PVC", pressure_class="PN10", pms_m=101.9, price=50.0, roughness_mm=0.01),
        CatalogPipe(id=2, dn=110, di_mm=99.4, material="PVC", pressure_class="PN10", pms_m=101.9, price=72.8, roughness_mm=0.01),
        CatalogPipe(id=3, dn=160, di_mm=147.6, material="PVC", pressure_class="PN10", pms_m=101.9, price=126.8, roughness_mm=0.01),
    ]
    nodes_z = {"A": 0.0, "M": 0.0, "B": 0.0}
    segments = [
        SegmentSpec(id="main", length_m=400.0, flow_m3s=0.03, max_velocity_ms=6.0),
        SegmentSpec(id="tail", length_m=30.0, flow_m3s=0.03, max_velocity_ms=6.0),
    ]
    kwargs = dict(
        node_ids_ordered=["A", "M", "B"], node_ground_z=nodes_z, segments_ordered=segments,
        upstream_level_max=100.0, upstream_level_min=100.0, min_pressure=None,
        downstream_residual_pressure=40.0, catalog=catalog, singular_loss_markup_pct=0.0,
        fluid_temperature_c=20.0,
    )
    without = solve_gravitaire_troncon(**kwargs)
    with_callback = solve_gravitaire_troncon(**kwargs, on_progress=lambda done, total: None)
    assert with_callback.alerts == without.alerts
    assert [(r.id, r.dn, r.material) for r in with_callback.segments] == [(r.id, r.dn, r.material) for r in without.segments]


def test_solve_refoulement_troncon_on_progress_reaches_done_equals_total():
    catalog = _catalog()
    nodes_z = {"P": 50.0, "R": 100.0}
    segments = [SegmentSpec(id="s1", length_m=2000.0, flow_m3s=0.04, max_velocity_ms=2.0)]
    calls: list[tuple[int, int]] = []
    result = solve_refoulement_troncon(
        node_ids_ordered=["P", "R"],
        node_ground_z=nodes_z,
        segments_ordered=segments,
        min_pressure=None,
        downstream_residual_pressure=20.0,
        catalog=catalog,
        singular_loss_markup_pct=10.0,
        fluid_temperature_c=20.0,
        on_progress=lambda done, total: calls.append((done, total)),
    )
    assert result.alerts == []
    assert calls
    assert calls[-1][0] == calls[-1][1]
    assert all(a[0] <= b[0] for a, b in zip(calls, calls[1:]))
