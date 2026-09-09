from hydrops_engine.topology import moving_average_smooth


def test_constant_profile_is_unchanged():
    points = [(float(i * 10), 100.0) for i in range(10)]
    smoothed = moving_average_smooth(points, window_m=50)
    assert all(z == 100.0 for _, z in smoothed)


def test_spike_is_attenuated():
    points = [(0.0, 100.0), (10.0, 100.0), (20.0, 500.0), (30.0, 100.0), (40.0, 100.0)]
    smoothed = moving_average_smooth(points, window_m=25)
    spike_index = 2
    assert smoothed[spike_index][1] < points[spike_index][1]


def test_zero_window_returns_input_unchanged():
    points = [(0.0, 10.0), (10.0, 20.0)]
    assert moving_average_smooth(points, window_m=0) == points


def test_output_has_same_length_and_pks_as_input():
    points = [(float(i), float(i) ** 1.3) for i in range(20)]
    smoothed = moving_average_smooth(points, window_m=3)
    assert len(smoothed) == len(points)
    assert [pk for pk, _ in smoothed] == [pk for pk, _ in points]
