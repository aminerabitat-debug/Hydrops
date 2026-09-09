import math

from hydrops_engine.topology import sample_at_step, total_length_m


def test_sample_includes_start_and_end():
    coords = [(0.0, 0.0), (0.0, 0.1)]
    samples = sample_at_step(coords, step_m=1000)
    assert samples[0].pk == 0.0
    assert math.isclose(samples[-1].pk, total_length_m(coords), rel_tol=1e-6)


def test_sample_is_monotonic_in_pk():
    coords = [(0.0, 0.0), (0.02, 0.03), (0.05, 0.01)]
    samples = sample_at_step(coords, step_m=500)
    pks = [s.pk for s in samples]
    assert pks == sorted(pks)
    assert len(set(pks)) == len(pks)  # pas de doublons


def test_sample_includes_original_vertices_as_breakpoints():
    coords = [(0.0, 0.0), (0.0, 0.05), (0.02, 0.05)]
    total = total_length_m(coords)
    mid_pk = sample_at_step([coords[0], coords[1]], 1_000_000)[-1].pk  # pk du sommet intermediaire seul
    samples = sample_at_step(coords, step_m=1_000_000)  # pas tres large : force a ne garder que les breakpoints
    pks = [round(s.pk, 3) for s in samples]
    assert round(mid_pk, 3) in pks
    assert round(total, 3) in pks


def test_sample_rejects_non_positive_step():
    try:
        sample_at_step([(0.0, 0.0), (0.0, 1.0)], step_m=0)
        assert False, "devait lever ValueError"
    except ValueError:
        pass
