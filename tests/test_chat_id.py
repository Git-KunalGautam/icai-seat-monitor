from unittest.mock import Mock

from src import chat_id


def test_helper_prints_ids_without_tokens_or_sending(monkeypatch, capsys):
    monkeypatch.setattr(chat_id, "load_dotenv", lambda: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:FAKE_TEST_TOKEN")
    session = Mock()
    monkeypatch.setattr(chat_id, "make_session", lambda trust: session)
    response = Mock(status_code=200)
    response.json.return_value = {"ok": True, "result": [
        {"message": {"chat": {"id": 42, "type": "private"}}},
        {"channel_post": {"chat": {"id": -100123, "type": "channel"}}},
    ]}
    monkeypatch.setattr(chat_id, "request", Mock(return_value=response))
    assert chat_id.main() == 0
    output = capsys.readouterr().out
    assert "TELEGRAM_CHAT_ID=42" in output
    assert "TELEGRAM_CHAT_ID=-100123" in output
    assert "FAKE_TEST_TOKEN" not in output
    session.post.assert_not_called()
    session.close.assert_called_once()


def test_helper_missing_token_never_requests(monkeypatch):
    monkeypatch.setattr(chat_id, "load_dotenv", lambda: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    transport = Mock(side_effect=AssertionError("Must not request"))
    monkeypatch.setattr(chat_id, "request", transport)
    assert chat_id.main() == 1
    transport.assert_not_called()
