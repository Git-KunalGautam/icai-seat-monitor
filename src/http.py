import logging
import time

import requests


class TransportError(RuntimeError):
    def __init__(self, message: str, retry_after: float = 0):
        super().__init__(message)
        self.retry_after = retry_after


def make_session(trust_env: bool = True) -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_env
    return session


def request(
    session: requests.Session, method: str, url: str, *, timeout: float,
    max_retries: int, service: str, **kwargs,
) -> requests.Response:
    """Bounded retry for read-only site postbacks and idempotent API reads.

    Never log raw exceptions: URLs can contain bot tokens or proxy credentials.
    Long Retry-After requests fail rather than retrying ahead of the server.
    """
    for attempt in range(max_retries + 1):
        delay = min(2 ** (attempt + 1), 30)
        try:
            response = session.request(method, url, timeout=(min(timeout, 10), timeout),
                                       allow_redirects=False, **kwargs)
        except requests.exceptions.SSLError:
            raise TransportError(f"{service}: TLS verification failed") from None
        except requests.RequestException:
            if attempt == max_retries:
                raise TransportError(f"{service}: network request failed") from None
        else:
            if response.status_code != 429 and response.status_code not in {500, 502, 503, 504}:
                return response
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    raise TransportError(f"{service}: server requested a later retry", retry_after=61) from None
            if attempt == max_retries or delay > 60:
                raise TransportError(f"{service}: transient HTTP {response.status_code}; retry later", retry_after=delay)
        logging.warning("%s: transient request failure; retry %d/%d", service, attempt + 1, max_retries)
        time.sleep(delay)
    raise AssertionError("unreachable")
