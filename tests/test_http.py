from unittest.mock import Mock

import pytest
import requests

from src.http import TransportError, request


def test_transient_requests_bounded_and_sanitized():
    session = Mock()
    session.request.side_effect = requests.ConnectionError("secret_url")
    with pytest.raises(TransportError) as caught:
        request(session, "GET", "https://example.test", timeout=30, max_retries=2, service="test")
    assert "secret_url" not in str(caught.value)
    assert session.request.call_count == 3


def test_retry_after_not_ignored():
    session = Mock()
    session.request.return_value = Mock(status_code=429, headers={"Retry-After": "120"})
    with pytest.raises(TransportError):
        request(session, "GET", "https://example.test", timeout=30, max_retries=3, service="test")
    assert session.request.call_count == 1


def test_tls_failure_is_not_retried_or_weakened():
    session = Mock()
    session.request.side_effect = requests.exceptions.SSLError("certificate failed")
    with pytest.raises(TransportError, match="TLS verification"):
        request(session, "GET", "https://example.test", timeout=30, max_retries=3, service="test")
    assert session.request.call_count == 1
