"""Suivi de progression des imports de trace — en memoire, process-local, meme principe que
SessionStore (docs/architecture/01-architecture-systeme.md §1.4). Un import KML/KMZ echantillonne
le DEM par lots (hydrops_api/services/dem.py) ; ce store permet au client de suivre l'avancement
(lots traites / total) via polling, plutot que de rester bloque sur une requete HTTP unique
pouvant durer plus d'une minute sur une trace longue (cas reel mesure : 68 km, 4659 points, ~1 min)
sans aucun retour avant la reponse finale.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

DEFAULT_JOB_TTL_SECONDS = 600.0  # 10 min : largement assez pour qu'un client termine son polling


class ImportJobNotFoundError(Exception):
    def __init__(self, job_id: str):
        super().__init__(f"Job d'import inconnu ou expire: {job_id}")
        self.job_id = job_id


@dataclass
class ImportJobState:
    id: str
    session_id: str
    status: str = "running"  # running | done | failed
    total_chunks: int = 0
    completed_chunks: int = 0
    trace: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


class ImportJobStore:
    def __init__(self, ttl_seconds: float = DEFAULT_JOB_TTL_SECONDS):
        self._jobs: dict[str, ImportJobState] = {}
        self._ttl = ttl_seconds
        self._tasks: set[asyncio.Task] = set()

    def create(self, session_id: str, total_chunks: int = 0) -> ImportJobState:
        job = ImportJobState(id=str(uuid.uuid4()), session_id=session_id, total_chunks=total_chunks)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> ImportJobState:
        job = self._jobs.get(job_id)
        if job is None:
            raise ImportJobNotFoundError(job_id)
        return job

    def update_progress(self, job_id: str, completed_chunks: int, total_chunks: int) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return  # session/job purges entre-temps : rien a mettre a jour, pas une erreur
        job.completed_chunks = completed_chunks
        job.total_chunks = total_chunks

    def mark_done(self, job_id: str, trace: dict) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = "done"
        job.trace = trace
        job.completed_chunks = job.total_chunks
        job.finished_at = time.time()

    def mark_failed(self, job_id: str, error: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = "failed"
        job.error = error
        job.finished_at = time.time()

    def track_task(self, task: asyncio.Task) -> None:
        """Garde une reference forte vers la tache de fond — asyncio ne garantit pas qu'une tache
        creee via create_task() sans reference conservee survive jusqu'a sa fin (elle peut etre
        ramassee par le GC en cours de route)."""
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def purge_expired(self) -> int:
        now = time.time()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status != "running" and job.finished_at is not None and (now - job.finished_at) > self._ttl
        ]
        for job_id in expired:
            del self._jobs[job_id]
        return len(expired)
