"""The published API refuses callers who are not signed in."""
from fastapi.testclient import TestClient

from backend.app import app


def test_local_dev_server_still_answers():
    client = TestClient(app)
    assert client.get('/api/v2/health').status_code == 200
    assert client.get('/').status_code == 200


def test_published_api_requires_a_signed_in_viewer(monkeypatch):
    monkeypatch.setenv('CURSOR_APP_ID', 'app-test')
    client = TestClient(app)
    denied = client.get('/api/v2/library')
    assert denied.status_code == 401
    assert denied.json()['error'] == 'Sign in required.'
    assert denied.headers['cache-control'] == 'private, no-store'
    assert client.get('/').status_code == 200
