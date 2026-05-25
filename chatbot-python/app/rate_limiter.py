from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Callable


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._max_requests = max_requests
        self._window = timedelta(seconds=window_seconds)
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self._now_provider()

    def check(self, key: str) -> None:
        now = self._now()
        bucket = self._events[key]
        cutoff = now - self._window

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= self._max_requests:
            raise RateLimitExceeded(
                "Has enviado demasiados mensajes. Intenta de nuevo en un momento."
            )

        bucket.append(now)
