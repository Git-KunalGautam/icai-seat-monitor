from dataclasses import replace
from pathlib import Path

import pytest
import requests

from src.config import load_settings
from src.models import Batch, Target


@pytest.fixture(autouse=True)
def no_network_or_sleep(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must never contact the network")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr("time.sleep", lambda seconds: None)


@pytest.fixture
def target():
    return Target("Central", "JAIPUR", "Advanced (ICITSS) MCS Course")


@pytest.fixture
def batch():
    return Batch("Central", "JAIPUR", "Advanced (ICITSS) MCS Course", "AdvICITSSMCS__JAIPUR_89",
                 0, "12/11/2026", "30/11/2026", "10-0-AM to 5-0-PM", "General", "2026-11-04T10:00:00+05:30")


@pytest.fixture
def fixture_html():
    return lambda name: (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")


@pytest.fixture
def settings(monkeypatch, tmp_path):
    # Tests deliberately never consume real Telegram credentials or .env files.
    monkeypatch.setattr("src.config.load_dotenv", lambda: None)
    for key in list(__import__("os").environ):
        if key.startswith(("TELEGRAM_", "DEFAULT_", "STATE_", "GITHUB_")) or key in {
            "ICAI_URL", "TIMEZONE", "MAX_RETRIES", "REQUEST_TIMEOUT", "HTTP_TRUST_ENV",
            "NOTIFY_ON_SEAT_INCREASE", "LOG_LEVEL"
        }:
            monkeypatch.delenv(key)
    config = tmp_path / "config.json"
    config.write_text('{"targets": []}', encoding="utf-8")
    return replace(load_settings(config), max_retries=0, state_path=tmp_path / "state.json")
