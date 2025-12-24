"""Caching utilities for API responses."""

import re
from pathlib import Path
from typing import Optional


class CacheManager:
    """Manages on-disk caching of API responses."""

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize cache manager.

        Args:
            cache_dir: Directory for cache storage. If None, caching is disabled.
        """
        self.cache_dir = cache_dir

    def read(self, key: str) -> Optional[str]:
        """
        Read cached content.

        Args:
            key: Cache key

        Returns:
            Cached content if exists, None otherwise
        """
        if not self.cache_dir:
            return None

        path = self._get_path(key)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def write(self, key: str, content: str) -> None:
        """
        Write content to cache.

        Args:
            key: Cache key
            content: Content to cache
        """
        if not self.cache_dir:
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._get_path(key)
        path.write_text(content, encoding="utf-8")

    def _get_path(self, key: str) -> Path:
        """Get file path for cache key."""
        safe_key = re.sub(r"[^A-Za-z0-9._-]+", "_", key)
        return self.cache_dir / f"{safe_key}.cache"
