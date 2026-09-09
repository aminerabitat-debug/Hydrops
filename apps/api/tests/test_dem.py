"""Tests de la recuperation d'altitudes DEM (hydrops_api.services.dem) — sans reseau reel :
les appels HTTP sont simules pour garder la suite deterministe et rapide (docs/architecture/09
§9.4). Couvre la cascade par fournisseur ET la parallelisation/cascade par LOT introduite apres
un cas reel (trace de 68 km, 4659 points, 55 s en sequentiel plein-lot — voir dem.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from hydrops_api.services.dem import (
    DemProvider,
    DemProviderError,
    OpenElevationDemProvider,
    OpenMeteoElevationProvider,
    OpenTopoDataProvider,
    build_dem_providers,
    fetch_elevations,
)


class _FakeProvider(DemProvider):
    def __init__(self, name: str, version: str, *, fail: bool = False, values: list[float] | None = None):
        self.source_name = name
        self.source_version = version
        self._fail = fail
        self._values = values or []
        self.calls: list[list[tuple[float, float]]] = []

    async def sample_batch(self, points):
        self.calls.append(list(points))
        if self._fail:
            raise DemProviderError(f"{self.source_name} indisponible")
        return self._values[: len(points)] if self._values else [0.0] * len(points)


@pytest.mark.asyncio
async def test_fetch_elevations_uses_first_provider_when_it_succeeds():
    first = _FakeProvider("A", "1", values=[10.0, 20.0])
    second = _FakeProvider("B", "1", values=[99.0, 99.0])

    result = await fetch_elevations([(0.0, 0.0), (1.0, 1.0)], [first, second])

    assert result.elevations == [10.0, 20.0]
    assert result.source_name == "A"
    assert second.calls == []  # jamais appele : le premier fournisseur a suffi


@pytest.mark.asyncio
async def test_fetch_elevations_falls_back_to_next_provider_on_failure():
    first = _FakeProvider("A", "1", fail=True)
    second = _FakeProvider("B", "2", values=[5.0])

    result = await fetch_elevations([(0.0, 0.0)], [first, second])

    assert result.elevations == [5.0]
    assert result.source_name == "B"
    assert result.source_version == "2"


@pytest.mark.asyncio
async def test_fetch_elevations_raises_when_all_providers_fail():
    providers = [_FakeProvider("A", "1", fail=True), _FakeProvider("B", "2", fail=True)]

    with pytest.raises(DemProviderError, match="A indisponible.*B indisponible"):
        await fetch_elevations([(0.0, 0.0)], providers)


@pytest.mark.asyncio
async def test_fetch_elevations_with_empty_points_short_circuits():
    provider = _FakeProvider("A", "1", fail=True)
    result = await fetch_elevations([], [provider])
    assert result.elevations == []
    assert provider.calls == []


def test_fetch_elevations_requires_at_least_one_provider():
    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(fetch_elevations([(0.0, 0.0)], []))


@pytest.mark.asyncio
async def test_fetch_elevations_splits_into_chunks_and_preserves_order():
    provider = _FakeProvider("A", "1")
    points = [(float(i), float(i)) for i in range(25)]

    async def echo_index(points_arg):
        provider.calls.append(list(points_arg))
        return [p[0] for p in points_arg]

    provider.sample_batch = echo_index  # type: ignore[method-assign]

    result = await fetch_elevations(points, [provider], chunk_size=10, max_concurrency=4)

    assert result.elevations == [float(i) for i in range(25)]
    assert len(provider.calls) == 3  # 10 + 10 + 5
    assert [len(c) for c in provider.calls] == [10, 10, 5]


@pytest.mark.asyncio
async def test_fetch_elevations_recovers_partial_batch_failure_without_redoing_succeeded_chunks():
    # Le premier fournisseur echoue systematiquement (simule un cas reel : rate limit / timeout
    # au milieu d'une longue trace) ; seul le lot en echec doit retenter sur le fournisseur B,
    # les autres lots reussis sur A ne doivent pas etre rejoues.
    class FlakyOnSecondChunk(DemProvider):
        source_name = "A"
        source_version = "1"

        def __init__(self):
            self.call_count = 0

        async def sample_batch(self, points):
            self.call_count += 1
            if self.call_count == 2:
                raise DemProviderError("A indisponible pour ce lot")
            return [1.0] * len(points)

    flaky = FlakyOnSecondChunk()
    backup = _FakeProvider("B", "2", values=[9.0] * 100)

    points = [(float(i), float(i)) for i in range(30)]
    result = await fetch_elevations(points, [flaky, backup], chunk_size=10, max_concurrency=1)

    assert len(result.elevations) == 30
    assert result.elevations[0:10] == [1.0] * 10  # premier lot : A a reussi
    assert result.elevations[10:20] == [9.0] * 10  # deuxieme lot : replie sur B
    assert result.elevations[20:30] == [1.0] * 10  # troisieme lot : A a reussi de nouveau
    assert result.source_name == "mixte"
    assert "A/1" in result.source_version
    assert "B/2" in result.source_version


def test_build_dem_providers_cascade_chains_all_three_real_providers():
    providers = build_dem_providers("cascade")
    assert [type(p) for p in providers] == [
        OpenMeteoElevationProvider,
        OpenTopoDataProvider,
        OpenElevationDemProvider,
    ]


def test_build_dem_providers_single_provider_modes():
    assert [type(p) for p in build_dem_providers("open_elevation")] == [OpenElevationDemProvider]
    assert [type(p) for p in build_dem_providers("open_meteo")] == [OpenMeteoElevationProvider]
    assert [type(p) for p in build_dem_providers("opentopodata")] == [OpenTopoDataProvider]


def _mock_response(json_body: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=json_body)
    return response


@pytest.mark.asyncio
async def test_open_meteo_provider_parses_response():
    provider = OpenMeteoElevationProvider()
    with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=_mock_response({"elevation": [12.0, 34.0]}))):
        result = await provider.sample_batch([(2.35, 48.85), (2.36, 48.86)])
    assert result == [12.0, 34.0]


@pytest.mark.asyncio
async def test_open_meteo_provider_rejects_malformed_response():
    provider = OpenMeteoElevationProvider()
    with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=_mock_response({"elevation": [12.0]}))):
        with pytest.raises(DemProviderError):
            await provider.sample_batch([(2.35, 48.85), (2.36, 48.86)])


@pytest.mark.asyncio
async def test_opentopodata_provider_parses_response():
    provider = OpenTopoDataProvider()
    body = {"results": [{"elevation": 100.0}, {"elevation": 200.0}]}
    with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=_mock_response(body))):
        result = await provider.sample_batch([(2.35, 48.85), (2.36, 48.86)])
    assert result == [100.0, 200.0]


@pytest.mark.asyncio
async def test_open_elevation_provider_parses_response():
    provider = OpenElevationDemProvider()
    body = {"results": [{"elevation": 1.0}]}
    with patch.object(httpx.AsyncClient, "post", new=AsyncMock(return_value=_mock_response(body))):
        result = await provider.sample_batch([(2.35, 48.85)])
    assert result == [1.0]


@pytest.mark.asyncio
async def test_provider_raises_dem_error_on_http_failure():
    provider = OpenMeteoElevationProvider()
    with patch.object(httpx.AsyncClient, "get", new=AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))):
        with pytest.raises(DemProviderError):
            await provider.sample_batch([(2.35, 48.85)])


def _mock_429_response() -> MagicMock:
    response = MagicMock()
    response.status_code = 429
    response.headers = {}
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=response)
    )
    return response


def _mock_200_response(json_body: dict) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=json_body)
    return response


@pytest.mark.asyncio
async def test_provider_retries_once_on_429_then_succeeds():
    # Cas reel observe : sous charge concurrente, les API publiques repondent parfois 429 sur un
    # lot isole — un backoff court doit suffire, sans basculer sur le fournisseur suivant.
    provider = OpenMeteoElevationProvider()
    responses = [_mock_429_response(), _mock_200_response({"elevation": [10.0]})]
    with (
        patch.object(httpx.AsyncClient, "get", new=AsyncMock(side_effect=responses)),
        patch("hydrops_api.services.dem.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        result = await provider.sample_batch([(2.35, 48.85)])
    assert result == [10.0]
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_gives_up_after_max_retries_on_persistent_429():
    provider = OpenMeteoElevationProvider()
    responses = [_mock_429_response(), _mock_429_response(), _mock_429_response()]
    with (
        patch.object(httpx.AsyncClient, "get", new=AsyncMock(side_effect=responses)),
        patch("hydrops_api.services.dem.asyncio.sleep", new=AsyncMock()),
    ):
        with pytest.raises(DemProviderError):
            await provider.sample_batch([(2.35, 48.85)])
