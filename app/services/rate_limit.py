import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    """Single-process global limiter that bounds expensive analysis calls."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._requests: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            while self._requests and self._requests[0] <= cutoff:
                self._requests.popleft()
            if len(self._requests) >= self.limit:
                return False
            self._requests.append(now)
            return True
