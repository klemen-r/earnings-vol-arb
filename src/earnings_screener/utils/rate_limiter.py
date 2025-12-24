"""Rate limiting for API requests."""

import threading
import time


class RateLimiter:
    """Thread-safe rate limiter for API requests."""

    def __init__(self, rate_per_sec: float):
        """
        Initialize rate limiter.

        Args:
            rate_per_sec: Maximum requests per second
        """
        self.rate_per_sec = max(rate_per_sec, 0.0)
        self.min_interval = 1.0 / self.rate_per_sec if self.rate_per_sec > 0 else 0.0
        self.lock = threading.Lock()
        self.next_time = 0.0

    def acquire(self) -> None:
        """Acquire permission to make a request, blocking if necessary."""
        if self.min_interval <= 0:
            return

        while True:
            with self.lock:
                now = time.monotonic()
                if now >= self.next_time:
                    self.next_time = now + self.min_interval
                    return
                wait = self.next_time - now
            time.sleep(wait)
