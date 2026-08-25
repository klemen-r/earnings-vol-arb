"""Tests for caching and rate limiting helpers."""

import time

from earnings_screener.utils.cache import CacheManager
from earnings_screener.utils.rate_limiter import RateLimiter


class TestCacheManager:
    def test_write_then_read_round_trip(self, tmp_path):
        cache = CacheManager(tmp_path)

        cache.write("AAPL", "payload")

        assert cache.read("AAPL") == "payload"

    def test_missing_key_reads_as_none(self, tmp_path):
        assert CacheManager(tmp_path).read("MSFT") is None

    def test_disabled_cache_never_touches_disk(self, tmp_path):
        cache = CacheManager(None)

        cache.write("AAPL", "payload")

        assert cache.read("AAPL") is None
        assert list(tmp_path.iterdir()) == []

    def test_unsafe_key_characters_are_sanitized(self, tmp_path):
        cache = CacheManager(tmp_path)

        cache.write("earnings/2026-01-15?full=1", "payload")

        written = list(tmp_path.iterdir())
        assert len(written) == 1
        assert "/" not in written[0].name
        assert "?" not in written[0].name

    def test_keys_differing_only_by_unsafe_characters_share_a_file(self, tmp_path):
        cache = CacheManager(tmp_path)

        cache.write("a/b", "first")
        cache.write("a?b", "second")

        assert cache.read("a/b") == "second"
        assert len(list(tmp_path.iterdir())) == 1

    def test_creates_the_cache_directory_on_demand(self, tmp_path):
        target = tmp_path / "nested" / "cache"
        cache = CacheManager(target)

        cache.write("AAPL", "payload")

        assert target.is_dir()


class TestRateLimiter:
    def test_interval_is_the_inverse_of_the_rate(self):
        assert RateLimiter(4.0).min_interval == 0.25

    def test_zero_rate_disables_limiting(self):
        limiter = RateLimiter(0)

        assert limiter.min_interval == 0.0

        start = time.monotonic()
        for _ in range(5):
            limiter.acquire()
        assert time.monotonic() - start < 0.05

    def test_negative_rate_is_clamped_to_zero(self):
        assert RateLimiter(-3).rate_per_sec == 0.0

    def test_consecutive_acquires_are_spaced_by_the_interval(self):
        limiter = RateLimiter(50.0)  # 20 ms apart

        start = time.monotonic()
        limiter.acquire()
        limiter.acquire()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.015
