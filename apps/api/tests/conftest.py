import os
import time
from pathlib import Path

# Force le fournisseur DEM deterministe/hors reseau pour tous les tests — le reseau ne doit
# jamais etre une condition de succes/echec d'une suite de tests (docs/architecture/09 §9.4).
os.environ["HYDROPS_DEM_PROVIDER"] = "synthetic"

import pytest
from fastapi.testclient import TestClient

from hydrops_api.core.config import get_settings
from hydrops_api.main import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session_id(client) -> str:
    response = client.post("/api/v1/sessions")
    assert response.status_code == 200
    return response.json()["session_id"]


@pytest.fixture
def project_state(client, session_id) -> dict:
    response = client.post(f"/api/v1/projects/new?session_id={session_id}", json={"name": "Projet Test"})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def sample_kml_bytes() -> bytes:
    return (FIXTURES_DIR / "sample_trace.kml").read_bytes()


@pytest.fixture
def sample_kmz_bytes() -> bytes:
    return (FIXTURES_DIR / "sample_trace.kmz").read_bytes()


@pytest.fixture
def branched_kml_bytes() -> bytes:
    return (FIXTURES_DIR / "branched_trace.kml").read_bytes()


@pytest.fixture
def import_trace(client):
    """L'import de trace est asynchrone (job + polling, cf. routers/traces.py) — ce helper POSTe
    le fichier puis interroge le job jusqu'a completion et retourne la reponse finale (soit la
    trace, soit leve une AssertionError avec le message d'erreur du job si echec), pour que les
    tests restent aussi simples a lire qu'avec l'ancien import synchrone."""

    def _import(session_id: str, filename: str, content: bytes, content_type: str) -> dict:
        response = client.post(
            f"/api/v1/projects/{session_id}/traces/import",
            files={"file": (filename, content, content_type)},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]

        for _ in range(200):
            job = client.get(f"/api/v1/projects/{session_id}/traces/import-jobs/{job_id}").json()
            if job["status"] != "running":
                break
            time.sleep(0.02)
        else:
            raise AssertionError(f"Job d'import {job_id} n'a jamais termine (toujours 'running')")

        if job["status"] == "failed":
            raise AssertionError(f"Job d'import {job_id} a echoue: {job['error']}")
        return job["trace"]

    return _import


@pytest.fixture
def run_calc(client):
    """Le calcul hydraulique est asynchrone (job + polling, cf. routers/network.py) — meme
    principe que `import_trace` ci-dessus. POSTe .../calcul puis interroge le job jusqu'a
    completion et retourne la reponse finale (meme forme que l'ancien retour synchrone : status/
    segments_updated/nodes_updated/alerts/reposition_suggestions), pour que les tests restent
    aussi simples a lire qu'avant. Si le serveur repond directement `needs_confirmation` (tronçon
    au-dela du seuil de sonde sans `confirmed=true`), la reponse brute est renvoyee telle quelle
    (pas de job a suivre) — a l'appelant de la reconnaitre via sa forme."""

    def _run(session_id: str, variant_id: str, **params) -> dict:
        response = client.post(
            f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul", params=params
        )
        if response.status_code != 202:
            return response.json()
        job_id = response.json()["job_id"]

        for _ in range(500):
            job = client.get(
                f"/api/v1/projects/{session_id}/variants/{variant_id}/calcul-jobs/{job_id}"
            ).json()
            if job["status"] != "running":
                break
            time.sleep(0.02)
        else:
            raise AssertionError(f"Job de calcul {job_id} n'a jamais termine (toujours 'running')")

        if job["status"] == "failed":
            raise AssertionError(f"Job de calcul {job_id} a echoue: {job['error']}")
        return job["result"]

    return _run
