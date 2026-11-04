"""Read chat IDs from recent bot updates; never sends messages or prints tokens."""
import logging
import os

from dotenv import load_dotenv

from .config import boolean
from .http import TransportError, make_session, request
from .logger import configure_logging


def main() -> int:
    configure_logging("INFO")
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logging.error("Set TELEGRAM_BOT_TOKEN in .env first")
        return 1
    session = None
    try:
        session = make_session(boolean("HTTP_TRUST_ENV", True))
        response = request(session, "GET", f"https://api.telegram.org/bot{token}/getUpdates",
                           timeout=30, max_retries=2, service="Telegram updates", params={"timeout": 0})
        body = response.json()
        if response.status_code != 200 or not isinstance(body, dict) or body.get("ok") is not True:
            logging.error("Cannot read updates (HTTP %d); check bot token and webhook configuration", response.status_code)
            return 1
        if not isinstance(body.get("result"), list):
            raise ValueError
        chats = {}
        for update in body["result"]:
            for kind in ("message", "channel_post", "my_chat_member"):
                chat = update.get(kind, {}).get("chat", {})
                if type(chat.get("id")) is int:
                    chats[chat["id"]] = chat.get("type", "unknown")
        if not chats:
            print("No recent chat updates. Send /start privately, or add the bot as channel admin and post a message, then retry.")
        for chat_id, kind in sorted(chats.items()):
            print(f"{kind}: TELEGRAM_CHAT_ID={chat_id}")
        return 0
    except (TransportError, ValueError, TypeError, AttributeError):
        # Do not print raw JSON/network exceptions that might contain the token.
        logging.error("Cannot read Telegram chat IDs; check network access and bot configuration")
        return 1
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main())
