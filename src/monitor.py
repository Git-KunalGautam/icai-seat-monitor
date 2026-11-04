from copy import deepcopy
from datetime import date, datetime, timedelta
import logging
import time

from .models import Batch
from .notifier import NotificationError


def update_observations(state: dict, batches: list[Batch], notify_on_increase: bool) -> dict:
    updated = deepcopy(state)
    seen = set()
    for batch in batches:
        if batch.key in seen:
            raise ValueError("Duplicate batch across monitoring targets")
        seen.add(batch.key)
        previous = updated["batches"].get(batch.key)
        old_seats = previous["available_seats"] if previous else 0
        pending = previous["notification_pending"] if previous else False
        delivered = previous["last_notified_seats"] if previous else None
        if batch.available_seats == 0:
            pending, delivered = False, None
        elif old_seats == 0 or (notify_on_increase and batch.available_seats > old_seats):
            pending = True
        record = {"available_seats": batch.available_seats, "notification_pending": pending,
                  "last_notified_seats": delivered, "to_date": batch.to_date,
                  "changed_at": previous["changed_at"] if previous else batch.last_checked_at}
        if record != previous:
            record["changed_at"] = batch.last_checked_at
        updated["batches"][batch.key] = record
    return updated


def prune_completed(state: dict, today: date, observed_keys: set[str]) -> None:
    # Keep one record per batch, with a 30-day buffer after completion.
    cutoff = today - timedelta(days=30)
    for key, record in list(state["batches"].items()):
        if key not in observed_keys and datetime.strptime(record["to_date"], "%d/%m/%Y").date() < cutoff:
            del state["batches"][key]


def run_monitor(state: dict, batches: list[Batch], store, notifier, *, notify_on_increase: bool,
                url: str, today: date) -> int:
    updated = update_observations(state, batches, notify_on_increase)
    prune_completed(updated, today, {b.key for b in batches})
    # Durable pending alerts before sending; never send when this checkpoint fails.
    store.save(updated)
    failures = 0
    for batch in batches:
        record = updated["batches"][batch.key]
        if not record["notification_pending"] or notifier is None:
            continue
        try:
            message_id = notifier.send(batch, url)
        except NotificationError as exc:
            logging.error("Alert failed for %s: %s", batch.batch_number, exc)
            failures += 1
            continue
        record["notification_pending"] = False
        record["last_notified_seats"] = batch.available_seats
        record["changed_at"] = batch.last_checked_at
        # Persist each confirmed delivery before attempting another alert.
        store.save(updated)
        logging.info("Telegram confirmed batch=%s seats=%d message_id=%d", batch.batch_number, batch.available_seats, message_id)
        # Telegram recommends spacing messages to the same chat.
        time.sleep(1)
    logging.info("Check complete: batches=%d positive=%d alert_failures=%d notifications_enabled=%s",
                 len(batches), sum(b.available_seats > 0 for b in batches), failures, notifier is not None)
    return failures
