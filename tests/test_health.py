from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoints(client: TestClient) -> None:
    for route in ("/health", "/healthz", "/live"):
        response = client.get(route)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
