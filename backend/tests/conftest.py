from __future__ import annotations

import pytest

from autodj.config.settings import Settings, load_settings


@pytest.fixture
def settings() -> Settings:
    """Settings from ``default.yaml`` only, ignoring any developer ``.env``."""
    return load_settings(env_file=None)
