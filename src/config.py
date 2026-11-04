from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .models import Target


class ConfigError(ValueError):
    pass


def boolean(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false"}:
        raise ConfigError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True)
class Settings:
    url: str
    targets: list[Target]
    token: str = field(repr=False)
    chat_id: str = field(repr=False)
    notifications_enabled: bool
    notify_on_increase: bool
    timezone: str
    timeout: float
    max_retries: int
    trust_env: bool
    backend: str
    state_path: Path
    state_branch: str
    repository: str
    github_token: str = field(repr=False)
    log_level: str


def load_settings(config_path: Path = Path("config.json")) -> Settings:
    load_dotenv()
    try:
        default = Target(
            os.getenv("DEFAULT_REGION", "Central"), os.getenv("DEFAULT_POU", "JAIPUR"),
            os.getenv("DEFAULT_COURSE", "Advanced (ICITSS) MCS Course"),
        )
        # config.json adds to the env-configured default target.
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("targets"), list):
            raise ConfigError("config.json must contain a targets array")
        targets = [default]
        for item in raw["targets"]:
            if not isinstance(item, dict) or set(item) != {"region", "pou", "course"}:
                raise ConfigError("Each target needs exactly region, pou and course")
            targets.append(Target(**item))
        for t in targets:
            if any(not isinstance(v, str) or not v.strip() for v in (t.region, t.pou, t.course)):
                raise ConfigError("Target labels must be nonempty strings")
        targets = list({t.identity: t for t in targets}.values())
        url = os.getenv("ICAI_URL", "https://icaionlineregistration.org/launchbatchdetail.aspx")
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in {
            "icaionlineregistration.org", "www.icaionlineregistration.org"
        } or parts.username or parts.password or parts.port not in (None, 443)
                or parts.path.lower() != "/launchbatchdetail.aspx" or parts.query or parts.fragment):
            raise ConfigError("ICAI_URL must be the official HTTPS launchbatchdetail.aspx page")
        timezone = os.getenv("TIMEZONE", "Asia/Kolkata")
        ZoneInfo(timezone)
        timeout = float(os.getenv("REQUEST_TIMEOUT", "30"))
        retries = int(os.getenv("MAX_RETRIES", "3"))
        if not 1 <= timeout <= 120 or not 0 <= retries <= 5:
            raise ConfigError("REQUEST_TIMEOUT must be 1..120; MAX_RETRIES must be 0..5")
        backend = os.getenv("STATE_BACKEND", "local")
        if backend not in {"local", "github"}:
            raise ConfigError("STATE_BACKEND must be local or github")
        return Settings(
            url, targets, os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""),
            boolean("TELEGRAM_NOTIFICATIONS_ENABLED", True), boolean("NOTIFY_ON_SEAT_INCREASE", True),
            timezone, timeout, retries, boolean("HTTP_TRUST_ENV", True), backend,
            Path(os.getenv("STATE_PATH", "data/local_state.json")), os.getenv("STATE_BRANCH", "main"),
            os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_TOKEN", ""), os.getenv("LOG_LEVEL", "INFO"),
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Do not include environment values or credential-bearing error strings.
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError("Invalid configuration; check config.json, numeric settings and TIMEZONE") from None
