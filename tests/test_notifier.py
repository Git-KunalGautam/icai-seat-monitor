from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests

from src.notifier import NotificationError, TelegramNotifier, format_message


def response(status=200, body=None):
    r = Mock(status_code=status)
    r.json.return_value = body if body is not None else {"ok": True, "result": {"message_id": 123}}
    return r


def notifier(session):
    return TelegramNotifier("123:FAKE_TEST_TOKEN", "-100123456", max_retries=2, session=session)


def test_message_fields_and_plain_text_escaping(batch):
    message = format_message(replace(batch, available_seats=3, batch_number="<batch>&*"), "https://example.test")
    for field in ["ICAI Seat Available", "3", "Central", "JAIPUR", batch.course, "<batch>&*",
                  "12/11/2026", "30/11/2026", batch.batch_time, "https://example.test", "Asia/Kolkata", "+05:30"]:
        assert field in message


def test_confirmed_success_and_channel_support(batch):
    session = Mock()
    session.post.return_value = response()
    assert notifier(session).send(batch, "https://example.test") == 123
    kwargs = session.post.call_args.kwargs
    assert kwargs["json"]["chat_id"] == "-100123456"
    assert "parse_mode" not in kwargs["json"]
    assert kwargs["timeout"] == (10, 30)
    assert kwargs["allow_redirects"] is False


@pytest.mark.parametrize("body", [{"ok": False}, {"ok": True, "result": {}}, {"ok": "true"}, [], None])
def test_invalid_or_rejected_response(batch, body):
    session = Mock()
    session.post.return_value = response(body=body if body is not None else {})
    with pytest.raises(NotificationError):
        notifier(session).send(batch, "https://example.test")


def test_invalid_json(batch):
    session = Mock()
    session.post.return_value = response()
    session.post.return_value.json.side_effect = ValueError("invalid")
    with pytest.raises(NotificationError):
        notifier(session).send(batch, "https://example.test")


def test_token_not_exposed_on_network_failure(batch):
    session = Mock()
    session.post.side_effect = requests.ReadTimeout("https://api.telegram.org/bot123:FAKE_TEST_TOKEN/sendMessage")
    with pytest.raises(NotificationError) as caught:
        notifier(session).send(batch, "https://example.test")
    assert "FAKE_TEST_TOKEN" not in str(caught.value)
    assert session.post.call_count == 1


def test_rate_limit_retry_and_bounded_failure(batch):
    session = Mock()
    session.post.side_effect = [response(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 3}}), response()]
    assert notifier(session).send(batch, "https://example.test") == 123
    assert session.post.call_count == 2
    session.post.side_effect = None
    session.post.return_value = response(503, {"ok": False, "error_code": 503})
    session.post.reset_mock()
    with pytest.raises(NotificationError):
        notifier(session).send(batch, "https://example.test")
    assert session.post.call_count == 3


def test_long_retry_after_does_not_retry_early(batch):
    session = Mock()
    session.post.return_value = response(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 100}})
    with pytest.raises(NotificationError):
        notifier(session).send(batch, "https://example.test")
    assert session.post.call_count == 1


def test_invalid_credentials_not_retried(batch):
    session = Mock()
    session.post.return_value = response(401, {"ok": False, "error_code": 401})
    with pytest.raises(NotificationError):
        notifier(session).send(batch, "https://example.test")
    assert session.post.call_count == 1
