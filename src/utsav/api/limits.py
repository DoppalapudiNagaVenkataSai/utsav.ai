"""Simple in-memory, per-IP sliding-window rate limiter for the AI endpoints."""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import HTTPException, Request, status

MAX_TRACKED_CLIENTS = 10_000


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if key not in self._hits and len(self._hits) >= MAX_TRACKED_CLIENTS:
                self._evict(now)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def _evict(self, now: float) -> None:
        stale = [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window]
        for k in stale:
            del self._hits[k]
        if len(self._hits) >= MAX_TRACKED_CLIENTS:  # still full: drop the oldest client
            del self._hits[min(self._hits, key=lambda k: self._hits[k][-1])]

    def __call__(self, request: Request) -> None:
        """FastAPI dependency."""
        client = request.client.host if request.client else "unknown"
        if not self.allow(client):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many AI requests; please wait a minute.",
                headers={"Retry-After": str(int(self.window))},
            )
