from __future__ import annotations

import json

import pytest

from autodj.logging_config import configure_logging, get_logger


def test_json_logs_are_structured_records(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")

    get_logger("test").info("transition_planned", session_id=42, stretch_ratio=0.988)

    record = json.loads(capsys.readouterr().out.strip())
    assert record["event"] == "transition_planned"
    assert record["session_id"] == 42
    assert record["stretch_ratio"] == 0.988
    assert record["level"] == "info"
    assert "timestamp" in record


def test_level_filtering_drops_quieter_events(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", "json")

    logger = get_logger("test")
    logger.info("ignored_event")
    logger.warning("kept_event")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert [json.loads(line)["event"] for line in lines] == ["kept_event"]
