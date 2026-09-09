import math

from hydrops_engine.topology import (
    cumulative_pk,
    haversine_distance_m,
    interpolate_lonlat_at_pk,
    interpolate_value_at_pk,
    total_length_m,
)


def test_haversine_one_degree_longitude_at_equator():
    # 1 degre de longitude a l'equateur vaut environ 111.32 km
    d = haversine_distance_m(0.0, 0.0, 1.0, 0.0)
    assert math.isclose(d, 111_320, rel_tol=0.01)


def test_haversine_zero_distance():
    assert haversine_distance_m(2.35, 48.85, 2.35, 48.85) == 0.0


def test_cumulative_pk_straight_line():
    coords = [(0.0, 0.0), (0.0, 0.01), (0.0, 0.02)]
    vertices = cumulative_pk(coords)
    assert vertices[0].pk == 0.0
    assert vertices[1].pk < vertices[2].pk
    # Trajet regulier : le deuxieme segment ajoute environ la meme distance que le premier
    assert math.isclose(vertices[1].pk, vertices[2].pk - vertices[1].pk, rel_tol=0.01)


def test_total_length_matches_last_vertex_pk():
    coords = [(0.0, 0.0), (0.0, 0.05), (0.01, 0.05)]
    assert total_length_m(coords) == cumulative_pk(coords)[-1].pk


def test_cumulative_pk_requires_at_least_two_points():
    try:
        cumulative_pk([(0.0, 0.0)])
        assert False, "devait lever ValueError"
    except ValueError:
        pass


def test_interpolate_lonlat_at_pk_midpoint():
    coords = [(0.0, 0.0), (0.0, 0.02)]
    total = total_length_m(coords)
    lon, lat = interpolate_lonlat_at_pk(coords, total / 2)
    assert math.isclose(lon, 0.0, abs_tol=1e-9)
    assert math.isclose(lat, 0.01, rel_tol=0.01)


def test_interpolate_lonlat_at_pk_clamps_out_of_bounds():
    coords = [(0.0, 0.0), (0.0, 0.02)]
    total = total_length_m(coords)
    assert interpolate_lonlat_at_pk(coords, -10.0) == interpolate_lonlat_at_pk(coords, 0.0)
    assert interpolate_lonlat_at_pk(coords, total + 1000) == interpolate_lonlat_at_pk(coords, total)


def test_interpolate_value_at_pk_midpoint():
    samples = [(0.0, 10.0), (100.0, 20.0)]
    assert math.isclose(interpolate_value_at_pk(samples, 50.0), 15.0)


def test_interpolate_value_at_pk_clamps_out_of_bounds():
    samples = [(0.0, 10.0), (100.0, 20.0)]
    assert interpolate_value_at_pk(samples, -5.0) == 10.0
    assert interpolate_value_at_pk(samples, 200.0) == 20.0
