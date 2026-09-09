from hydrops_engine.topology import detect_high_low_points


def test_detects_clear_peak_and_valley():
    profile = [
        (0.0, 100.0), (10.0, 100.0),
        (20.0, 150.0),  # pic net
        (30.0, 100.0), (40.0, 100.0),
        (50.0, 60.0),   # creux net
        (60.0, 100.0), (70.0, 100.0),
    ]
    candidates = detect_high_low_points(profile, min_prominence=5.0)
    kinds_at_pk = {c.pk: c.kind for c in candidates}
    assert kinds_at_pk.get(20.0) == "high_point"
    assert kinds_at_pk.get(50.0) == "low_point"


def test_does_not_flag_noise_below_threshold():
    # variations de +/-0.1 m, en dessous du seuil de proeminence par defaut
    profile = [(float(i * 10), 100.0 + (0.1 if i % 2 == 0 else -0.1)) for i in range(10)]
    candidates = detect_high_low_points(profile, min_prominence=0.5)
    assert candidates == []


def test_flat_profile_has_no_candidates():
    profile = [(float(i * 10), 100.0) for i in range(10)]
    assert detect_high_low_points(profile) == []


def test_short_profile_returns_empty():
    assert detect_high_low_points([(0.0, 10.0), (10.0, 20.0)]) == []
