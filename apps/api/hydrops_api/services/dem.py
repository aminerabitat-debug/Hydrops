"""Service DEM — docs/architecture/06-sig-dem.md.

Cascade de fournisseurs d'altitude publics, dans le meme ordre que la page de reference
fournie par l'utilisateur (page_carte_profil_itineraire.html) : Open-Meteo Elevation en premier
(rapide, sans limite de debit stricte), puis OpenTopoData ASTER30m (topo dediee), puis
Open-Elevation en dernier recours. Si un fournisseur echoue (reseau, timeout, format), le suivant
est tente ; l'echec n'est remonte que si TOUS echouent — jamais de repli silencieux vers une
source synthetique en production (§17 : pas de resultat presente comme valide sans etre trace
jusqu'a sa source reelle).

Chaque fournisseur ne traite qu'UN lot de points par appel (pas de boucle de chunking interne) :
c'est `fetch_elevations` qui decoupe en lots, les recupere EN PARALLELE (concurrence bornee) et
applique la cascade PAR LOT — pas sur la liste entiere. Une trace reelle de 68 km (cas mesure :
4659 points, ~55 s en sequentiel plein-lot) illustre pourquoi c'est important : en sequentiel,
un echec transitoire sur un lot au milieu de la liste faisait rejouer TOUTE la liste sur le
fournisseur suivant, plusieurs fois si necessaire. Ici, seul le lot concerne retente, et tous les
lots progressent en parallele.

Mesure sur ce meme cas reel : au-dela d'une poignee de requetes simultanees, les TROIS API
publiques (Open-Meteo, OpenTopoData, Open-Elevation) repondent 429 Too Many Requests EN MEME
TEMPS sur un lot — une concurrence trop genereuse peut donc faire echouer un lot entier au lieu
de l'accelerer. `_with_retry` absorbe les 429 isoles par un backoff court avant de
recourir a la cascade, et `DEFAULT_MAX_CONCURRENCY` reste volontairement modeste.

Copernicus GLO-30 (docs/architecture/06 §6.2) reste la cible a terme pour un cache de tuiles
durable ; cette cascade d'API publiques est le choix pragmatique de ce lot, derriere la meme
interface DemProvider (donc remplacable sans impact sur le reste de l'application).
"""

from __future__ import annotations

import abc
import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass

import httpx

DEFAULT_CHUNK_SIZE = 100
DEFAULT_MAX_CONCURRENCY = 3
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BASE_DELAY_S = 0.75


async def _with_retry(
    make_request,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY_S,
) -> httpx.Response:
    """Reessaie `make_request()` sur 429 (rate limit) avec un backoff exponentiel court, en
    respectant l'entete Retry-After si le serveur la fournit. Une seule requete 429 isolee ne doit
    pas faire basculer tout un lot vers le fournisseur suivant (et in fine vers le plus lent)
    alors qu'attendre une fraction de seconde suffirait.

    Prend un callable (pas directement client.get/post) pour que chaque fournisseur garde son
    appel httpx propre (get vs post, params vs json) — et pour que les tests puissent continuer a
    mocker `httpx.AsyncClient.get`/`.post` directement plutot qu'un `.request` generique."""
    response: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        response = await make_request()
        if response.status_code != 429 or attempt == max_retries:
            break
        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else base_delay * (2**attempt)
        await asyncio.sleep(delay)
    assert response is not None
    response.raise_for_status()
    return response


class DemProviderError(Exception):
    """Le fournisseur DEM n'a pas pu repondre — a traduire en alerte MISSING_ELEVATION_DATA (§17),
    jamais en repli silencieux vers une autre source de donnees d'altitude."""


class DemProvider(abc.ABC):
    source_name: str
    source_version: str

    @abc.abstractmethod
    async def sample_batch(self, points: list[tuple[float, float]]) -> list[float]:
        """points: UN lot de (lon, lat) WGS84 (voir DEFAULT_CHUNK_SIZE — le decoupage en lots est
        la responsabilite de l'appelant, pas du fournisseur). Retourne l'altitude en metres,
        meme ordre."""


class OpenMeteoElevationProvider(DemProvider):
    source_name = "open-meteo"
    source_version = "v1"

    def __init__(self, base_url: str = "https://api.open-meteo.com/v1/elevation", timeout: float = 15.0):
        self._base_url = base_url
        self._timeout = timeout

    async def sample_batch(self, points: list[tuple[float, float]]) -> list[float]:
        if not points:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                latitudes = ",".join(f"{lat:.6f}" for _, lat in points)
                longitudes = ",".join(f"{lon:.6f}" for lon, _ in points)
                response = await _with_retry(
                    lambda: client.get(
                        self._base_url, params={"latitude": latitudes, "longitude": longitudes}
                    )
                )
                values = response.json()["elevation"]
                if not isinstance(values, list) or len(values) != len(points):
                    raise DemProviderError("Reponse Open-Meteo invalide (format ou taille inattendue)")
                return [float(v) for v in values]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise DemProviderError(f"Echec de l'echantillonnage DEM ({self.source_name}): {e}") from e


class OpenTopoDataProvider(DemProvider):
    source_name = "opentopodata"
    source_version = "aster30m"

    def __init__(self, base_url: str = "https://api.opentopodata.org/v1/aster30m", timeout: float = 20.0):
        self._base_url = base_url
        self._timeout = timeout

    async def sample_batch(self, points: list[tuple[float, float]]) -> list[float]:
        if not points:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                locations = "|".join(f"{lat:.6f},{lon:.6f}" for lon, lat in points)
                response = await _with_retry(lambda: client.get(self._base_url, params={"locations": locations}))
                results = response.json().get("results")
                if not isinstance(results, list) or len(results) != len(points):
                    raise DemProviderError("Reponse OpenTopoData invalide (format ou taille inattendue)")
                return [float(r["elevation"]) for r in results]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise DemProviderError(f"Echec de l'echantillonnage DEM ({self.source_name}): {e}") from e


class OpenElevationDemProvider(DemProvider):
    source_name = "open-elevation"
    source_version = "v1"

    def __init__(self, base_url: str = "https://api.open-elevation.com/api/v1/lookup", timeout: float = 20.0):
        self._base_url = base_url
        self._timeout = timeout

    async def sample_batch(self, points: list[tuple[float, float]]) -> list[float]:
        if not points:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                locations = [{"latitude": lat, "longitude": lon} for lon, lat in points]
                response = await _with_retry(lambda: client.post(self._base_url, json={"locations": locations}))
                results = response.json()["results"]
                return [float(r["elevation"]) for r in results]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise DemProviderError(f"Echec de l'echantillonnage DEM ({self.source_name}): {e}") from e


class SyntheticDemProvider(DemProvider):
    """Source deterministe, hors reseau — utilisee en test et en developpement offline
    (docs/architecture/09-strategie-tests.md §9.4 : le determinisme des tests ne doit pas
    dependre d'un service reseau tiers). Ne jamais utiliser comme repli silencieux en production."""

    source_name = "synthetic"
    source_version = "v1"

    async def sample_batch(self, points: list[tuple[float, float]]) -> list[float]:
        return [50.0 + 40.0 * math.sin(lon * 10.0) + 20.0 * math.cos(lat * 7.0) for lon, lat in points]


@dataclass
class ElevationBatchResult:
    elevations: list[float]
    source_name: str
    source_version: str


async def fetch_elevations(
    points: list[tuple[float, float]],
    providers: list[DemProvider],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    on_progress: Callable[[int, int], None] | None = None,
) -> ElevationBatchResult:
    """Decoupe `points` en lots de `chunk_size`, les recupere en parallele (au plus
    `max_concurrency` requetes HTTP simultanees, par courtoisie envers des API publiques
    gratuites) et applique la cascade de `providers` INDEPENDAMMENT sur chaque lot — un lot en
    echec sur le premier fournisseur retente seul sur le suivant, sans invalider le travail deja
    reussi sur les autres lots.

    `on_progress(completed_chunks, total_chunks)` est appele une premiere fois des que le nombre
    total de lots est connu (avant toute requete), puis a chaque lot termine — c'est ce qui
    alimente la barre de progression cote client (un import peut prendre plus d'une minute sur une
    trace longue, voir hydrops_api/core/import_job_store.py).

    `source_name`/`source_version` du resultat identifient le fournisseur reellement utilise ; si
    des lots differents ont fini par repondre via des fournisseurs differents (cascade partielle),
    c'est signale explicitement ("mixte") plutot que d'annoncer une source unique trompeuse
    (§17/V1-11 : la tracabilite ne doit jamais masquer l'origine reelle d'une donnee)."""
    if not providers:
        raise ValueError("Au moins un fournisseur DEM est requis")
    if not points:
        return ElevationBatchResult([], providers[0].source_name, providers[0].source_version)

    chunks = [points[i : i + chunk_size] for i in range(0, len(points), chunk_size)]
    total_chunks = len(chunks)
    semaphore = asyncio.Semaphore(max_concurrency)
    completed_chunks = 0

    if on_progress:
        on_progress(0, total_chunks)

    async def fetch_chunk(chunk: list[tuple[float, float]]) -> tuple[list[float], str, str]:
        nonlocal completed_chunks
        errors: list[str] = []
        async with semaphore:
            for provider in providers:
                try:
                    values = await provider.sample_batch(chunk)
                    completed_chunks += 1
                    if on_progress:
                        on_progress(completed_chunks, total_chunks)
                    return values, provider.source_name, provider.source_version
                except DemProviderError as e:
                    errors.append(str(e))
        raise DemProviderError("Tous les fournisseurs DEM ont echoue pour un lot: " + " | ".join(errors))

    chunk_results = await asyncio.gather(*(fetch_chunk(chunk) for chunk in chunks))

    elevations: list[float] = []
    sources_used: dict[tuple[str, str], None] = {}  # dict = set ordonne (ordre d'apparition)
    for values, name, version in chunk_results:
        elevations.extend(values)
        sources_used[(name, version)] = None

    if len(sources_used) == 1:
        (source_name, source_version) = next(iter(sources_used))
    else:
        source_name = "mixte"
        source_version = "+".join(f"{n}/{v}" for n, v in sources_used)

    return ElevationBatchResult(elevations, source_name, source_version)


def build_dem_providers(name: str) -> list[DemProvider]:
    if name == "synthetic":
        return [SyntheticDemProvider()]
    if name == "open_elevation":
        return [OpenElevationDemProvider()]
    if name == "open_meteo":
        return [OpenMeteoElevationProvider()]
    if name == "opentopodata":
        return [OpenTopoDataProvider()]
    if name == "cascade":
        return [OpenMeteoElevationProvider(), OpenTopoDataProvider(), OpenElevationDemProvider()]
    raise ValueError(f"Fournisseur DEM inconnu: {name}")
