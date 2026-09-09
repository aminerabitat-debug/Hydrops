from __future__ import annotations

from fastapi import HTTPException, Request

from hydropack.serializer import ProjectPackage

from .session_store import ProjectNotOpenError, SessionNotFoundError, SessionStore


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


def require_package(store: SessionStore, session_id: str) -> ProjectPackage:
    try:
        return store.get_package(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotOpenError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


def require_session(store: SessionStore, session_id: str):
    try:
        return store.get(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
