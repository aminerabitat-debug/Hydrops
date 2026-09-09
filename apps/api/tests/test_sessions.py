def test_create_session_returns_id_and_expiry(client):
    response = client.post("/api/v1/sessions")
    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert body["expires_at"] > 0


def test_heartbeat_extends_expiry(client, session_id):
    first = client.post("/api/v1/sessions")
    response = client.post(f"/api/v1/sessions/{session_id}/heartbeat")
    assert response.status_code == 200
    assert response.json()["session_id"] == session_id


def test_heartbeat_unknown_session_returns_404(client):
    response = client.post("/api/v1/sessions/does-not-exist/heartbeat")
    assert response.status_code == 404


def test_delete_session_purges_it(client, session_id):
    response = client.delete(f"/api/v1/sessions/{session_id}")
    assert response.status_code == 204
    # Toute operation ulterieure sur cette session doit echouer (V1-10 : rien ne subsiste)
    response = client.get(f"/api/v1/projects/{session_id}")
    assert response.status_code == 404


def test_delete_unknown_session_returns_404(client):
    response = client.delete("/api/v1/sessions/does-not-exist")
    assert response.status_code == 404
