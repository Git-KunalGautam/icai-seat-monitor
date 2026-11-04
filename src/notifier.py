import time
from zoneinfo import ZoneInfo
from datetime import datetime

import requests

from .http import make_session
from .models import Batch


class NotificationError(RuntimeError):
    pass


def format_message(batch: Batch, url: str) -> str:
    checked = datetime.fromisoformat(batch.last_checked_at).astimezone(ZoneInfo("Asia/Kolkata"))
    return (
        "ICAI Seat Available\n\n"
        f"Available Seats: {batch.available_seats}\n"
        f"Region: {batch.region}\nPOU: {batch.pou}\nCourse: {batch.course}\n"
        f"Batch Number: {batch.batch_number}\n"
        f"Start Date: {batch.from_date}\nEnd Date: {batch.to_date}\n"
        f"Batch Timing: {batch.batch_time}\nOpen For: {batch.open_for}\n\n"
        f"Registration: {url}\n"
        f"Last Checked: {checked.isoformat(timespec='seconds')} (Asia/Kolkata)\n\n"
        "Check the website to register. Seats may change before registration."
    )


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, *, timeout=30, max_retries=3,
                 trust_env=True, session=None):
        if not token or not chat_id:
            raise NotificationError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or disable notifications")
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id, self.timeout, self.max_retries = chat_id, timeout, max_retries
        self.session = session or make_session(trust_env)

    def close(self) -> None:
        self.session.close()

    def send(self, batch: Batch, url: str) -> int:
        message = format_message(batch, url)
        if len(message) > 4096:
            raise NotificationError("Telegram message exceeds 4096 characters; inspect website fields")
        for attempt in range(self.max_retries + 1):
            delay = min(2 ** (attempt + 1), 30)
            try:
                response = self.session.post(
                    self._url, json={"chat_id": self.chat_id, "text": message,
                                     "link_preview_options": {"is_disabled": True}},
                    timeout=(min(self.timeout, 10), self.timeout), allow_redirects=False,
                )
            except requests.ConnectTimeout:
                if attempt == self.max_retries:
                    raise NotificationError("Telegram connect timeout; alert remains pending") from None
            except requests.RequestException:
                # A timeout/reset after submission may already have delivered the message.
                # Avoid blind retries within this run; retain pending state for the next check.
                raise NotificationError("Telegram delivery unconfirmed after network failure; alert remains pending") from None
            else:
                try:
                    body = response.json()
                    if not isinstance(body, dict):
                        raise ValueError
                except ValueError:
                    raise NotificationError("Telegram returned an invalid response; alert remains pending") from None
                result = body.get("result")
                if response.status_code == 200 and body.get("ok") is True:
                    message_id = result.get("message_id") if isinstance(result, dict) else None
                    if type(message_id) is not int or message_id <= 0:
                        raise NotificationError("Telegram success lacks message_id; delivery unconfirmed")
                    return message_id
                error = body.get("error_code", response.status_code)
                if body.get("ok") is not False or error not in {429, 500, 502, 503, 504}:
                    raise NotificationError(f"Telegram rejected request (HTTP {response.status_code}); check chat access and credentials")
                if error == 429:
                    parameters = body.get("parameters", {})
                    retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
                    if type(retry_after) is not int or retry_after < 0:
                        raise NotificationError("Telegram rate limit without valid retry_after; retry next run")
                    delay = max(delay, retry_after)
                if attempt == self.max_retries or delay > 60:
                    raise NotificationError("Telegram transient failure; alert remains pending for a later run")
            time.sleep(delay)
        raise NotificationError("Telegram delivery not confirmed")
