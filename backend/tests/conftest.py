from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from autodj.api.app import create_app
from autodj.config.settings import Settings, load_settings


@pytest.fixture
def settings() -> Settings:
    """Settings from ``default.yaml`` only, ignoring any developer ``.env``."""
    return load_settings(env_file=None)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
