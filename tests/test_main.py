from unittest.mock import Mock

from src import main
from src.models import ScrapeResult
from src.scraper import ScrapeError


def test_dry_run_never_initializes_notifier_or_state(settings, batch, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["monitor", "--dry-run"])
    monkeypatch.setattr(main, "load_settings", lambda p: settings)
    monkeypatch.setattr(main, "TelegramNotifier", Mock(side_effect=AssertionError("Must not send")))
    monkeypatch.setattr(main, "LocalStateStore", Mock(side_effect=AssertionError("Must not mutate")))
    scraper = Mock()
    scraper.fetch.return_value = ScrapeResult([batch])
    monkeypatch.setattr(main, "ICAIScraper", lambda settings: scraper)
    assert main.main() == 0
    assert batch.batch_number in capsys.readouterr().out
    scraper.close.assert_called_once()


def test_scraping_error_preserves_state_and_sends_nothing(settings, monkeypatch):
    monkeypatch.setattr("sys.argv", ["monitor"])
    monkeypatch.setattr(main, "load_settings", lambda p: settings)
    notifier, store, scraper = Mock(), Mock(), Mock()
    scraper.fetch.side_effect = ScrapeError("malformed site")
    monkeypatch.setattr(main, "TelegramNotifier", lambda *a, **k: notifier)
    monkeypatch.setattr(main, "LocalStateStore", lambda *a: store)
    monkeypatch.setattr(main, "ICAIScraper", lambda *a: scraper)
    assert main.main() == 1
    store.save.assert_not_called()
    notifier.send.assert_not_called()
