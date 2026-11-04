from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from src.monitor import run_monitor
from src.notifier import NotificationError
from src.state import LocalStateStore, StateError


def check(batch, store, notifier, seats, *, increase=True):
    state = store.load()
    current = replace(batch, available_seats=seats)
    errors = run_monitor(state, [current], store, notifier, notify_on_increase=increase,
                         url="https://icaionlineregistration.org/launchbatchdetail.aspx", today=date(2026, 11, 4))
    return store.load(), errors


def test_full_transition_sequence_and_no_duplicates(batch, tmp_path):
    store, notifier = LocalStateStore(tmp_path / "state.json"), Mock()
    notifier.send.return_value = 123
    expected = [0, 0, 1, 1, 1, 1, 2]
    for seats, count in zip([0, 0, 3, 3, 3, 0, 2], expected):
        state, errors = check(batch, store, notifier, seats)
        assert errors == 0
        assert notifier.send.call_count == count
        assert state["batches"][batch.key]["available_seats"] == seats


def test_new_positive_increase_decrease_and_zero(batch, tmp_path):
    store, notifier = LocalStateStore(tmp_path / "state.json"), Mock()
    notifier.send.return_value = 123
    for seats, count in [(2, 1), (5, 2), (3, 2), (0, 2), (1, 3)]:
        state, _ = check(batch, store, notifier, seats)
        assert notifier.send.call_count == count
    assert not state["batches"][batch.key]["notification_pending"]


def test_increase_disabled(batch, tmp_path):
    store, notifier = LocalStateStore(tmp_path / "state.json"), Mock()
    notifier.send.return_value = 123
    check(batch, store, notifier, 2, increase=False)
    state, _ = check(batch, store, notifier, 5, increase=False)
    assert notifier.send.call_count == 1
    assert state["batches"][batch.key]["available_seats"] == 5


def test_failed_alert_retried_even_if_seats_decrease(batch, tmp_path):
    store, notifier = LocalStateStore(tmp_path / "state.json"), Mock()
    notifier.send.side_effect = NotificationError("synthetic failure")
    state, errors = check(batch, store, notifier, 3)
    assert errors == 1
    assert state["batches"][batch.key]["notification_pending"]
    assert state["batches"][batch.key]["last_notified_seats"] is None
    notifier.send.side_effect = None
    notifier.send.return_value = 123
    state, errors = check(batch, store, notifier, 1)
    assert errors == 0
    assert state["batches"][batch.key]["last_notified_seats"] == 1


def test_zero_cancels_pending_notification(batch, tmp_path):
    store, notifier = LocalStateStore(tmp_path / "state.json"), Mock()
    notifier.send.side_effect = NotificationError("synthetic failure")
    check(batch, store, notifier, 3)
    state, _ = check(batch, store, notifier, 0)
    assert notifier.send.call_count == 1
    assert not state["batches"][batch.key]["notification_pending"]


def test_disabled_notifications_remain_pending(batch, tmp_path):
    store = LocalStateStore(tmp_path / "state.json")
    state, _ = check(batch, store, None, 3)
    assert state["batches"][batch.key]["notification_pending"]
    notifier = Mock()
    notifier.send.return_value = 123
    check(batch, store, notifier, 3)
    notifier.send.assert_called_once()


def test_multiple_batches_partial_delivery_persists(batch, tmp_path):
    store = LocalStateStore(tmp_path / "state.json")
    batches = [replace(batch, batch_number=f"batch_{n}", available_seats=2) for n in range(3)]
    notifier = Mock()
    notifier.send.side_effect = [123, NotificationError("synthetic failure"), 125]
    errors = run_monitor(store.load(), batches, store, notifier, notify_on_increase=True,
                         url="https://example.test", today=date(2026, 11, 4))
    assert errors == 1
    state = store.load()
    assert [state["batches"][b.key]["notification_pending"] for b in batches] == [False, True, False]
    notifier.send.side_effect = None
    notifier.send.return_value = 126
    notifier.reset_mock()
    run_monitor(state, list(reversed(batches)), store, notifier, notify_on_increase=True,
                url="https://example.test", today=date(2026, 11, 4))
    notifier.send.assert_called_once_with(batches[1], "https://example.test")


def test_checkpoint_failure_prevents_sends(batch, tmp_path):
    store = LocalStateStore(tmp_path / "state.json")
    state = store.load()
    store.save = Mock(side_effect=StateError("disk full"))
    notifier = Mock()
    with pytest.raises(StateError):
        run_monitor(state, [replace(batch, available_seats=2)], store, notifier,
                    notify_on_increase=True, url="https://example.test", today=date(2026, 11, 4))
    notifier.send.assert_not_called()


def test_identical_observations_do_not_write_each_run(batch, tmp_path, monkeypatch):
    store = LocalStateStore(tmp_path / "state.json")
    check(batch, store, None, 0)
    replace_file = Mock(side_effect=AssertionError("unchanged state must not write"))
    monkeypatch.setattr("src.state.os.replace", replace_file)
    later = replace(batch, last_checked_at="2026-11-04T10:15:00+05:30")
    check(later, store, None, 0)
    replace_file.assert_not_called()
