import argparse
from dataclasses import asdict
from datetime import datetime
import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ConfigError, load_settings
from .http import TransportError
from .logger import configure_logging
from .monitor import run_monitor
from .notifier import NotificationError, TelegramNotifier
from .parser import ParseError
from .scraper import ICAIScraper, ScrapeError
from .state import GitHubStateStore, LocalStateStore, StateError


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ICAI public batch availability once, then exit")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--dry-run", action="store_true", help="Fetch live batches without sending alerts or reading/writing state")
    args = parser.parse_args()
    configure_logging("INFO")
    scraper = notifier = store = None
    try:
        settings = load_settings(args.config)
        configure_logging(settings.log_level)
        if settings.notifications_enabled and not args.dry_run:
            notifier = TelegramNotifier(settings.token, settings.chat_id, timeout=settings.timeout,
                                        max_retries=settings.max_retries, trust_env=settings.trust_env)
        state = None
        if not args.dry_run:
            store = (GitHubStateStore(settings.repository, settings.state_branch, settings.github_token,
                                      timeout=settings.timeout, max_retries=settings.max_retries,
                                      trust_env=settings.trust_env)
                     if settings.backend == "github" else LocalStateStore(settings.state_path))
            state = store.load()
        scraper = ICAIScraper(settings)
        batches = []
        # Validate all targets before mutating state or sending any messages.
        for target in settings.targets:
            result = scraper.fetch(target)
            batches.extend(result.batches)
            logging.info("Scraped region=%s pou=%s course=%s batches=%d explicit_no_batches=%s",
                         target.region, target.pou, target.course, len(result.batches), result.no_batches)
        if args.dry_run:
            print(json.dumps([asdict(b) for b in batches], ensure_ascii=False, indent=2))
            return 0
        failures = run_monitor(state, batches, store, notifier, notify_on_increase=settings.notify_on_increase,
                               url=settings.url, today=datetime.now(ZoneInfo(settings.timezone)).date())
        return 1 if failures else 0
    except (ConfigError, TransportError, ScrapeError, ParseError, NotificationError, StateError, ValueError) as exc:
        logging.error("Monitoring failed: %s", exc)
        return 1
    finally:
        for resource in (scraper, notifier, store):
            if resource is not None and hasattr(resource, "close"):
                resource.close()


if __name__ == "__main__":
    raise SystemExit(main())
