import json

import pytest

from src.config import ConfigError, load_settings


def test_additional_targets_and_deduplication(settings, tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"targets": [
        {"region": " CENTRAL ", "pou": "jaipur", "course": "Advanced (ICITSS) MCS Course"},
        {"region": "Central", "pou": "JAIPUR", "course": "AICITSS - Advanced Information Technology"},
    ]}), encoding="utf-8")
    result = load_settings(path)
    assert len(result.targets) == 2
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "DO_NOT_PRINT")
    monkeypatch.setenv("GITHUB_TOKEN", "ALSO_SECRET")
    assert "DO_NOT_PRINT" not in repr(load_settings(path))
    assert "ALSO_SECRET" not in repr(load_settings(path))


@pytest.mark.parametrize("key,value", [("NOTIFY_ON_SEAT_INCREASE", "yes"), ("REQUEST_TIMEOUT", "0"),
    ("MAX_RETRIES", "99"), ("TIMEZONE", "Not/AZone"), ("ICAI_URL", "https://attacker.test/page"),
    ("ICAI_URL", "https://user:secret@icaionlineregistration.org/launchbatchdetail.aspx")])
def test_invalid_config_fails_without_leaking_values(settings, tmp_path, monkeypatch, key, value):
    path = tmp_path / "config.json"
    path.write_text('{"targets": []}', encoding="utf-8")
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigError) as caught:
        load_settings(path)
    assert "secret" not in str(caught.value)
