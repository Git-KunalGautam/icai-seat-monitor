import base64
from copy import deepcopy
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote

from .http import TransportError, make_session, request


class StateError(RuntimeError):
    pass


def empty_state() -> dict:
    return {"version": 1, "batches": {}}


def validate_state(state: object) -> dict:
    try:
        if not isinstance(state, dict) or set(state) != {"version", "batches"}:
            raise ValueError
        if type(state["version"]) is not int or state["version"] != 1 or not isinstance(state["batches"], dict):
            raise ValueError
        for key, record in state["batches"].items():
            identity = json.loads(key)
            if not isinstance(identity, list) or len(identity) != 4 or any(not isinstance(v, str) or not v for v in identity):
                raise ValueError
            if not isinstance(record, dict) or set(record) != {
                "available_seats", "notification_pending", "last_notified_seats", "to_date", "changed_at"
            }:
                raise ValueError
            seats, delivered = record["available_seats"], record["last_notified_seats"]
            if type(seats) is not int or seats < 0 or type(record["notification_pending"]) is not bool:
                raise ValueError
            if delivered is not None and (type(delivered) is not int or delivered <= 0):
                raise ValueError
            if seats == 0 and (record["notification_pending"] or delivered is not None):
                raise ValueError
            if seats > 0 and not record["notification_pending"] and delivered is None:
                raise ValueError
            datetime.strptime(record["to_date"], "%d/%m/%Y")
            if datetime.fromisoformat(record["changed_at"]).tzinfo is None:
                raise ValueError
        return state
    except (ValueError, TypeError, KeyError, OverflowError):
        raise StateError("State is corrupted or incompatible; restore it before sending alerts") from None


def decode_state(raw: str) -> dict:
    try:
        return validate_state(json.loads(raw))
    except (ValueError, TypeError):
        raise StateError("State is corrupted; restore it before sending alerts") from None


def encode_state(state: dict) -> str:
    validate_state(state)
    return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class LocalStateStore:
    def __init__(self, path: Path):
        self.path = path
        self._saved = None

    def load(self) -> dict:
        try:
            if self.path.exists():
                state = decode_state(self.path.read_text(encoding="utf-8"))
            else:
                logging.warning("Local state missing; starting with no delivery history")
                state = empty_state()
            self._saved = deepcopy(state)
            return state
        except (OSError, UnicodeError):
            raise StateError("Cannot read local state") from None

    def save(self, state: dict) -> None:
        raw = encode_state(state)
        if state == self._saved and self.path.exists():
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self._saved = deepcopy(state)
        except OSError:
            raise StateError("Cannot atomically save local state; stopping alerts") from None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


class GitHubStateStore:
    """Commit state through the Contents API using a file-SHA compare-and-swap.

    Every load uses the branch tip, not the workflow's possibly stale checkout.
    A concurrent edit to the state file is never silently merged or overwritten.
    """

    def __init__(self, repository: str, branch: str, token: str, *, timeout=30,
                 max_retries=3, trust_env=True, session=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token or not branch:
            raise StateError("GitHub backend requires GITHUB_REPOSITORY, STATE_BRANCH and GITHUB_TOKEN")
        self.url = f"https://api.github.com/repos/{repository}/contents/data/seat_state.json"
        self.branch, self.timeout, self.max_retries = branch, timeout, max_retries
        self.session = session or make_session(trust_env)
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28"})
        self._sha = None
        self._saved = None

    def close(self) -> None:
        self.session.close()

    def _read(self) -> tuple[str, dict]:
        response = request(self.session, "GET", self.url, params={"ref": self.branch},
                           timeout=self.timeout, max_retries=self.max_retries, service="GitHub state")
        if response.status_code == 404:
            raise StateError("GitHub state missing or inaccessible; commit data/seat_state.json and check branch/token permissions")
        if response.status_code != 200:
            raise StateError(f"Cannot read GitHub state: HTTP {response.status_code}")
        try:
            body = response.json()
            if body["type"] != "file" or body["encoding"] != "base64" or not body["sha"]:
                raise ValueError
            raw = base64.b64decode(body["content"]).decode("utf-8")
            return body["sha"], decode_state(raw)
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise StateError("Invalid GitHub Contents response or corrupted remote state") from None

    def load(self) -> dict:
        self._sha, state = self._read()
        self._saved = deepcopy(state)
        return state

    def save(self, state: dict) -> None:
        raw = encode_state(state)
        if self._sha is None:
            raise StateError("Load remote state before saving")
        if self._saved == state:
            return
        payload = {"message": "Update ICAI seat state [skip ci]", "branch": self.branch,
                   "sha": self._sha, "content": base64.b64encode(raw.encode("utf-8")).decode("ascii")}
        for attempt in range(self.max_retries + 1):
            retry_delay = min(2 ** (attempt + 1), 30)
            try:
                # On uncertain PUT outcomes, read back before attempting another commit.
                response = request(self.session, "PUT", self.url, json=payload, timeout=self.timeout,
                                   max_retries=0, service="GitHub state")
                if response.status_code not in {200, 201, 409, 422}:
                    raise StateError(f"Cannot commit GitHub state: HTTP {response.status_code}")
            except TransportError as exc:
                if exc.retry_after > 60:
                    raise StateError("GitHub requested a later retry; state was not confirmed") from None
                retry_delay = max(retry_delay, exc.retry_after)
                # Respect Retry-After before even attempting reconciliation reads.
                if exc.retry_after:
                    time.sleep(retry_delay)
            remote_sha, remote_state = self._read()
            if remote_state == state:
                self._sha, self._saved = remote_sha, deepcopy(state)
                return
            if remote_sha != self._sha:
                raise StateError("Concurrent remote state edit detected; refusing stale overwrite; rerun after inspection")
            if attempt < self.max_retries:
                time.sleep(retry_delay)
        raise StateError("GitHub state commit was not confirmed; stopping alerts")
