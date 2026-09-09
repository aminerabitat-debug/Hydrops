"""Tests unitaires directs du SessionStore — purge et confidentialite (V1-10),
docs/architecture/09-strategie-tests.md §9.6."""

import time

import pytest

from hydrops_api.core.session_store import ProjectNotOpenError, SessionNotFoundError, SessionStore


def test_create_get_roundtrip():
    store = SessionStore(ttl_seconds=60)
    state = store.create()
    fetched = store.get(state.id)
    assert fetched.id == state.id


def test_delete_purges_session_immediately():
    store = SessionStore(ttl_seconds=60)
    state = store.create()
    store.delete(state.id)
    with pytest.raises(SessionNotFoundError):
        store.get(state.id)


def test_expired_session_is_unreachable_and_purged_on_access():
    store = SessionStore(ttl_seconds=0.05)
    state = store.create()
    time.sleep(0.1)
    with pytest.raises(SessionNotFoundError):
        store.get(state.id)
    assert store.active_session_count() == 0  # nettoyee au moment de l'acces, pas seulement marquee


def test_purge_expired_removes_only_expired_sessions():
    store = SessionStore(ttl_seconds=0.05)
    expiring = store.create()
    fresh = store.create()
    store._sessions[fresh.id].expires_at = time.time() + 60  # simule une session encore active

    time.sleep(0.1)
    purged_count = store.purge_expired()

    assert purged_count == 1
    with pytest.raises(SessionNotFoundError):
        store.get(expiring.id)
    assert store.get(fresh.id).id == fresh.id


def test_get_package_without_project_raises():
    store = SessionStore(ttl_seconds=60)
    state = store.create()
    with pytest.raises(ProjectNotOpenError):
        store.get_package(state.id)
