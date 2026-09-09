from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..core.deps import get_session_store, require_session
from ..core.session_store import SessionNotFoundError

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("")
def create_session(request: Request):
    store = get_session_store(request)
    state = store.create()
    return {"session_id": state.id, "expires_at": state.expires_at}


@router.post("/{session_id}/heartbeat")
def heartbeat(session_id: str, request: Request):
    store = get_session_store(request)
    try:
        state = store.heartbeat(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"session_id": state.id, "expires_at": state.expires_at}


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request):
    store = get_session_store(request)
    require_session(store, session_id)  # 404 explicite si deja purgee, plutot qu'un 204 trompeur
    store.delete(session_id)
