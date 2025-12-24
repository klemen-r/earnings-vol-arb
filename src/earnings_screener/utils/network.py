"""Network utilities for HTTP requests."""

import logging
import random
import threading
import time
from typing import Optional

import requests

from ..config import BACKOFF_BASE, MAX_RETRIES, REQUEST_TIMEOUT, USER_AGENT
from .cache import CacheManager
from .rate_limiter import RateLimiter


class HttpClient:
    """Thread-safe HTTP client with rate limiting and caching."""

    def __init__(
        self,
        limiter: Optional[RateLimiter] = None,
        cache: Optional[CacheManager] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize HTTP client.

        Args:
            limiter: Rate limiter instance
            cache: Cache manager instance
            logger: Logger instance
        """
        self.limiter = limiter
        self.cache = cache
        self.logger = logger or logging.getLogger(__name__)
        self._local = threading.local()

    def _get_session(self) -> requests.Session:
        """Get thread-local session."""
        if not hasattr(self._local, "session"):
            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})
            self._local.session = session
        return self._local.session

    def get(self, url: str, cache_key: Optional[str] = None) -> str:
        """
        Perform GET request with caching and retry logic.

        Args:
            url: URL to fetch
            cache_key: Optional cache key. If provided and cache is enabled,
                      will check cache before making request.

        Returns:
            Response content

        Raises:
            RuntimeError: If request fails after all retries
        """
        # Check cache first
        if self.cache and cache_key:
            cached = self.cache.read(cache_key)
            if cached is not None:
                self.logger.debug(f"Cache hit: {cache_key}")
                return cached

        # Make request with retry logic
        session = self._get_session()

        for attempt in range(1, MAX_RETRIES + 1):
            if self.limiter:
                self.limiter.acquire()

            try:
                response = session.get(url, timeout=REQUEST_TIMEOUT)

                if response.status_code == 200:
                    content = response.text

                    # Cache successful response
                    if self.cache and cache_key:
                        self.cache.write(cache_key, content)

                    # Random delay to be polite
                    time.sleep(random.uniform(0.3, 0.7))
                    return content

                # Retry on rate limit or server errors
                if response.status_code in (429,) or 500 <= response.status_code < 600:
                    if attempt < MAX_RETRIES:
                        delay = BACKOFF_BASE ** attempt + random.uniform(0.2, 0.8)
                        self.logger.debug(
                            f"HTTP {response.status_code} on {url}, "
                            f"retry {attempt}/{MAX_RETRIES} after {delay:.1f}s"
                        )
                        time.sleep(delay)
                        continue

                raise RuntimeError(f"HTTP {response.status_code}: {url}")

            except requests.RequestException as exc:
                if attempt < MAX_RETRIES:
                    delay = BACKOFF_BASE ** attempt + random.uniform(0.2, 0.8)
                    self.logger.debug(
                        f"Request error on {url}, "
                        f"retry {attempt}/{MAX_RETRIES} after {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Request failed after {MAX_RETRIES} retries: {exc}")

        raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts")
