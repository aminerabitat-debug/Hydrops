"""Espace de travail ephemere de session — schema `session` de docs/architecture/01-architecture-systeme.md §1.4.

Implementation Lot 1 : dictionnaire process-local en memoire. C'est deja conforme a l'exigence
centrale (V1-10 : rien ne survit durablement) et suffisant pour un usage interne mono-instance.
A remplacer par un backend PostgreSQL/PostGIS pour un deploiement multi-process/multi-instance
(docs/architecture/08-sessions-confidentialite.md) — cette classe est le point d'injection unique
pour ce changement, le reste de l'API ne connait que son interface (create/get/heartbeat/delete/
purge_expired/get_package/set_package).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from hydropack.serializer import ProjectPackage

DEFAULT_TTL_SECONDS = 4 * 60 * 60


class SessionNotFoundError(Exception):
    def __init__(self, session_id: str):
        super().__init__(f"Session inconnue ou expiree: {session_id}")
        self.session_id = session_id


class ProjectNotOpenError(Exception):
    def __init__(self, session_id: str):
        super().__init__(f"Aucun projet ouvert dans la session {session_id}")
        self.session_id = session_id


@dataclass
class SessionState:
    id: str
    created_at: float
    expires_at: float
    package: ProjectPackage | None = None


class SessionStore:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, SessionState] = {}

    def create(self) -> SessionState:
        now = time.time()
        session_id = str(uuid.uuid4())
        state = SessionState(id=session_id, created_at=now, expires_at=now + self._ttl_seconds)
        self._sessions[session_id] = state
        return state

    def get(self, session_id: str) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None or state.expires_at < time.time():
            self._sessions.pop(session_id, None)
            raise SessionNotFoundError(session_id)
        return state

    def heartbeat(self, session_id: str) -> SessionState:
        state = self.get(session_id)
        state.expires_at = time.time() + self._ttl_seconds
        return state

    def delete(self, session_id: str) -> None:
        """Purge immediate et definitive — aucune trace de la session ne subsiste (V1-10)."""
        self._sessions.pop(session_id, None)

    def purge_expired(self) -> int:
        """Balayage des sessions dont le TTL est depasse (§8.2). Retourne le nombre purge."""
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if s.expires_at < now]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    def set_package(self, session_id: str, package: ProjectPackage) -> None:
        state = self.get(session_id)
        state.package = package

    def get_package(self, session_id: str) -> ProjectPackage:
        state = self.get(session_id)
        if state.package is None:
            raise ProjectNotOpenError(session_id)
        return state.package

    def active_session_count(self) -> int:
        return len(self._sessions)
