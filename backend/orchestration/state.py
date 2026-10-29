"""
VEXA — Shared, versioned run state

``SharedState`` is the single place where a run's intermediate results live.
Every write creates a new immutable version (nothing is overwritten), every
read can be attributed to an agent, and observers can subscribe to writes.

How architectures use it
------------------------
- Sequential / Hierarchical / Event-Driven pass data directly between steps
  (function arguments, manager hand-offs, event payloads). SharedState is an
  audit mirror: the runtime records every agent output here, so state changes
  are explicit and traceable, but agents do not *read* from it.
- Blackboard *coordinates through it*: knowledge sources obtain their inputs
  only via ``read`` and publish only via ``write``; the controller schedules
  them by inspecting the state. See ``blackboard.py``.

Standard keys (shared vocabulary across architectures)
------------------------------------------------------
requirement, requirement_analysis, project_analysis, implementation_plan,
code_changes, test_result, debug_report, verification
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

STANDARD_KEYS: tuple[str, ...] = (
    "requirement",
    "requirement_analysis",
    "project_analysis",
    "implementation_plan",
    "code_changes",
    "test_result",
    "debug_report",
    "verification",
)


class StateEntry(BaseModel):
    """One immutable version of one state key."""

    entry_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    seq: int = Field(description="Global write order within the run (1, 2, 3, ...)")
    key: str
    version: int
    author: str
    value_type: str
    value: Any = Field(description="JSON-serialisable snapshot of the value")
    written_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    derived_from: list[str] = Field(
        default_factory=list, description="entry_ids this value was computed from (provenance)",
    )


class StateAccess(BaseModel):
    seq: int
    kind: Literal["read", "write"]
    key: str
    agent: str
    version: int | None
    entry_id: str | None
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _snapshot(value: Any) -> tuple[str, Any]:
    if isinstance(value, BaseModel):
        return type(value).__name__, value.model_dump(mode="json")
    return type(value).__name__, value


class SharedState:
    """Thread-safe, append-only, access-logged key/value store for one run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._lock = threading.RLock()
        self._history: dict[str, list[StateEntry]] = {}
        self._objects: dict[str, Any] = {}  # latest typed object per key (not serialised)
        self._log: list[StateAccess] = []
        self._subscribers: list[Callable[[StateEntry], None]] = []
        self._write_seq = 0
        self.on_access: Callable[[StateAccess], None] | None = None  # tracing hook

    # -- writes ----------------------------------------------------------

    def write(self, key: str, value: Any, author: str, derived_from: list[str] | None = None) -> StateEntry:
        with self._lock:
            versions = self._history.setdefault(key, [])
            value_type, snap = _snapshot(value)
            self._write_seq += 1
            entry = StateEntry(
                seq=self._write_seq, key=key, version=len(versions) + 1, author=author,
                value_type=value_type, value=snap, derived_from=list(derived_from or []),
            )
            versions.append(entry)
            self._objects[key] = value
            access = StateAccess(
                seq=len(self._log) + 1, kind="write", key=key, agent=author,
                version=entry.version, entry_id=entry.entry_id,
            )
            self._log.append(access)
            subscribers = list(self._subscribers)
        if self.on_access:
            self.on_access(access)
        for fn in subscribers:  # outside the lock: subscribers may read
            fn(entry)
        return entry

    # -- reads -----------------------------------------------------------

    def read(self, key: str, reader: str) -> Any | None:
        """Return the latest typed value for *key* and log the access."""
        with self._lock:
            latest = self._history.get(key, [None])[-1]
            access = StateAccess(
                seq=len(self._log) + 1, kind="read", key=key, agent=reader,
                version=latest.version if latest else None,
                entry_id=latest.entry_id if latest else None,
            )
            self._log.append(access)
            value = self._objects.get(key)
        if self.on_access:
            self.on_access(access)
        return value

    def latest(self, key: str) -> StateEntry | None:
        """Latest entry metadata without logging a read (for schedulers/UI)."""
        with self._lock:
            versions = self._history.get(key)
            return versions[-1] if versions else None

    def version(self, key: str) -> int:
        entry = self.latest(key)
        return entry.version if entry else 0

    def has(self, key: str) -> bool:
        return self.version(key) > 0

    def seq_of(self, key: str) -> int:
        """Global write sequence of the latest version of *key* (0 if absent)."""
        entry = self.latest(key)
        return entry.seq if entry else 0

    def peek(self, key: str) -> Any | None:
        """Latest typed value without logging a read (controllers / schedulers only)."""
        with self._lock:
            return self._objects.get(key)

    def history(self, key: str) -> list[StateEntry]:
        with self._lock:
            return list(self._history.get(key, []))

    def subscribe(self, fn: Callable[[StateEntry], None]) -> None:
        with self._lock:
            self._subscribers.append(fn)

    # -- export ----------------------------------------------------------

    @property
    def access_log(self) -> list[StateAccess]:
        with self._lock:
            return list(self._log)

    def entries(self) -> list[StateEntry]:
        with self._lock:
            out = [e for versions in self._history.values() for e in versions]
        return sorted(out, key=lambda e: e.seq)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.model_dump(mode="json") for e in self.entries()],
            "access_log": [a.model_dump(mode="json") for a in self.access_log],
        }
