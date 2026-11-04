from datetime import datetime, timezone
import json
import logging
import re


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        # Defense in depth; network exceptions themselves are never logged.
        message = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[REDACTED]", message)
        return json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname, "event": message,
        }, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)
    # urllib3 DEBUG prints request paths, which contain Telegram tokens.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
