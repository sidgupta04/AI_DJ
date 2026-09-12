from __future__ import annotations

from fastapi.testclient import TestClient

from autodj import __version__
from autodj.config.settings import Settings


def test_health_reports_versions(client: TestClient, settings: Settings) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_version": __version__,
        "analysis_version": settings.analysis.version,
    }
