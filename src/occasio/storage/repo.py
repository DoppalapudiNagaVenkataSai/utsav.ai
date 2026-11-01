"""SQLite plan repository. Parameterised queries only; plans stored as JSON."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from occasio.core.models import Plan

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data       TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class StoredPlan:
    id: str
    created_at: datetime
    updated_at: datetime
    plan: Plan


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class PlanRepository:
    """One shared connection guarded by a lock; fine for a single-user local app."""

    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._conn:
            if str(path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_SCHEMA)

    def create(self, plan: Plan) -> StoredPlan:
        stored = StoredPlan(id=uuid.uuid4().hex, created_at=_now(), updated_at=_now(), plan=plan)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO plans (id, created_at, updated_at, data) VALUES (?, ?, ?, ?)",
                (stored.id, stored.created_at.isoformat(), stored.updated_at.isoformat(),
                 plan.model_dump_json()),
            )  # fmt: skip
        return stored

    def get(self, plan_id: str) -> StoredPlan | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, created_at, updated_at, data FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            return None
        return StoredPlan(
            id=row[0],
            created_at=datetime.fromisoformat(row[1]),
            updated_at=datetime.fromisoformat(row[2]),
            plan=Plan.model_validate_json(row[3]),
        )

    def update(self, plan_id: str, plan: Plan) -> StoredPlan | None:
        now = _now()
        with self._lock, self._conn:
            row = self._conn.execute(
                "UPDATE plans SET data = ?, updated_at = ? WHERE id = ? RETURNING created_at",
                (plan.model_dump_json(), now.isoformat(), plan_id),
            ).fetchone()
        if row is None:
            return None
        return StoredPlan(
            id=plan_id, created_at=datetime.fromisoformat(row[0]), updated_at=now, plan=plan
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
