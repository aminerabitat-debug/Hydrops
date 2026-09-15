"""Suivi de progression des calculs hydrauliques — en memoire, process-local, meme principe que
ImportJobStore/SessionStore (docs/architecture/01-architecture-systeme.md §1.4). Depuis la
suppression du pas d'echantillonnage hydraulique fixe (consigne utilisateur : "enleve ce pas
hydraulique... meme si ca va prendre plus de temps"), un tronçon peut desormais compter des
milliers de piquets fins (pleine resolution DEM, ~20 m) au lieu de quelques centaines — le calcul
(boucle de telescopage, hydrops_engine) peut donc durer bien plus qu'un aller-retour HTTP unique.
Ce store permet au client de suivre l'avancement (unites de travail completees/total) via polling,
avec le meme patron que le suivi d'import de trace (cf. import_job_store.py)."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field


DEFAULT_JOB_TTL_SECONDS = 600.0  # 10 min : largement assez pour qu'un client termine son polling


class CalcJobNotFoundError(Exception):
    def __init__(self, job_id: str):
        super().__init__(f"Job de calcul inconnu ou expire: {job_id}")
        self.job_id = job_id


@dataclass
class CalcJobState:
    id: str
    session_id: str
    status: str = "running"  # running | done | failed
    completed_units: float = 0.0
    total_units: float = 0.0
    result: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


class CalcJobStore:
    def __init__(self, ttl_seconds: float = DEFAULT_JOB_TTL_SECONDS):
        self._jobs: dict[str, CalcJobState] = {}
        self._ttl = ttl_seconds
        self._tasks: set[asyncio.Task] = set()

    def create(self, session_id: str, total_units: float = 0.0) -> CalcJobState:
        job = CalcJobState(id=str(uuid.uuid4()), session_id=session_id, total_units=total_units)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> CalcJobState:
        job = self._jobs.get(job_id)
        if job is None:
            raise CalcJobNotFoundError(job_id)
        return job

    def update_progress(self, job_id: str, completed_units: float, total_units: float) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return  # session/job purges entre-temps : rien a mettre a jour, pas une erreur
        job.completed_units = completed_units
        job.total_units = total_units

    def mark_done(self, job_id: str, result: dict) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = "done"
        job.result = result
        job.completed_units = job.total_units
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
