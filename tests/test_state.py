import base64
from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests

from src.monitor import update_observations
from src.state import GitHubStateStore, LocalStateStore, StateError, empty_state, encode_state


def remote(state, sha="original"):
    body = {"type": "file", "sha": sha, "encoding": "base64",
            "content": base64.b64encode(encode_state(state).encode()).decode()}
    return Mock(status_code=200, json=Mock(return_value=body), headers={})


def github(session, retries=2):
    return GitHubStateStore("owner/repo", "main", "TEST_TOKEN", max_retries=retries, session=session)


def test_missing_local_state_and_atomic_roundtrip(tmp_path, batch):
    store = LocalStateStore(tmp_path / "nested" / "state.json")
    assert store.load() == empty_state()
    state = update_observations(empty_state(), [batch], True)
    store.save(state)
    assert LocalStateStore(store.path).load() == state
    assert list(store.path.parent.glob("*.tmp")) == []


@pytest.mark.parametrize("raw", ["", "{broken", "[]", '{"version": 99, "batches": {}}',
                              '{"version": 1, "batches": {"batch": {}}}'])
def test_corrupted_state_never_reset_silently(tmp_path, raw):
    path = tmp_path / "state.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(StateError):
        LocalStateStore(path).load()
    assert path.read_text(encoding="utf-8") == raw


def test_invalid_record_rejected(batch):
    state = update_observations(empty_state(), [batch], True)
    state["batches"][batch.key]["available_seats"] = True
    with pytest.raises(StateError):
        encode_state(state)


def test_github_commit_and_skip_identical_state(batch):
    session = Mock()
    updated = update_observations(empty_state(), [batch], True)
    session.request.side_effect = [remote(empty_state()), Mock(status_code=200, headers={}), remote(updated, "new")]
    store = github(session)
    assert store.load() == empty_state()
    store.save(updated)
    assert session.request.call_count == 3
    store.save(updated)
    assert session.request.call_count == 3
    put = session.request.call_args_list[1]
    assert put.args[0] == "PUT"
    assert put.kwargs["json"]["sha"] == "original"
    assert put.kwargs["json"]["branch"] == "main"


def test_github_conflict_retry_when_file_unchanged(batch):
    session = Mock()
    updated = update_observations(empty_state(), [batch], True)
    session.request.side_effect = [remote(empty_state()), Mock(status_code=409, headers={}), remote(empty_state()),
                                   Mock(status_code=200, headers={}), remote(updated, "new")]
    store = github(session)
    store.load()
    store.save(updated)
    assert session.request.call_count == 5


def test_github_conflicting_state_refuses_overwrite(batch):
    session = Mock()
    desired = update_observations(empty_state(), [batch], True)
    other = update_observations(empty_state(), [replace(batch, available_seats=4)], True)
    session.request.side_effect = [remote(empty_state()), Mock(status_code=409, headers={}), remote(other, "concurrent")]
    store = github(session)
    store.load()
    with pytest.raises(StateError, match="Concurrent"):
        store.save(desired)
    assert session.request.call_count == 3


def test_github_lost_put_response_reconciles_without_duplicate_commit(batch):
    session = Mock()
    desired = update_observations(empty_state(), [batch], True)
    session.request.side_effect = [remote(empty_state()), requests.ReadTimeout("unknown outcome"), remote(desired, "new")]
    store = github(session)
    store.load()
    store.save(desired)
    assert session.request.call_count == 3


def test_github_missing_state_fails_closed():
    session = Mock()
    session.request.return_value = Mock(status_code=404, headers={})
    with pytest.raises(StateError, match="missing or inaccessible"):
        github(session).load()


def test_github_long_retry_after_is_respected(batch):
    session = Mock()
    session.request.side_effect = [remote(empty_state()), Mock(status_code=429, headers={"Retry-After": "120"})]
    store = github(session)
    store.load()
    with pytest.raises(StateError, match="later retry"):
        store.save(update_observations(empty_state(), [batch], True))
    assert session.request.call_count == 2
