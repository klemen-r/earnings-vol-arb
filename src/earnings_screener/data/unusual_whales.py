"""UnusualWhales earnings data scraper."""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    PlaywrightTimeout = Exception

from ..config import UNUSUAL_WHALES_URL, USER_AGENT
from ..utils import CacheManager


class UnusualWhalesScraper:
    """Scrape historical earnings data from UnusualWhales."""

    def __init__(self, cache: Optional[CacheManager] = None, logger: Optional[logging.Logger] = None):
        """
        Initialize scraper.

        Args:
            cache: Optional cache manager
            logger: Optional logger
        """
        self.cache = cache
        self.logger = logger or logging.getLogger(__name__)

        if not PLAYWRIGHT_AVAILABLE:
            self.logger.warning(
                "Playwright not available. Install with: "
                "pip install playwright && playwright install chromium"
            )

    def get_stats(self, ticker: str) -> Tuple[Optional[float], Optional[float], str]:
        """
        Get historical earnings stats for ticker.

        Returns win rate and average profit for short straddle strategy.
        Win rate: % of times actual move < implied move
        Avg profit: Average of (implied - |actual|) in percentage points

        Args:
            ticker: Stock symbol

        Returns:
            Tuple of (win_rate, avg_profit, status)
            status: "ok", "missing", "empty", or "unavailable"
        """
        if not PLAYWRIGHT_AVAILABLE:
            return None, None, "unavailable"

        # Check cache
        cache_key = f"uw_{ticker}"
        if self.cache:
            cached = self.cache.read(cache_key)
            if cached:
                try:
                    data = json.loads(cached)
                    implied = data.get("implied", [])
                    actual = data.get("actual", [])

                    if implied and actual:
                        win_rate, avg_profit = self._calculate_stats(implied, actual)
                        return win_rate, avg_profit, "ok"
                except json.JSONDecodeError:
                    pass

        # Scrape data
        implied_moves, actual_moves = self._scrape_earnings_data(ticker)

        if not implied_moves:
            return None, None, "missing"

        if not actual_moves or len(implied_moves) != len(actual_moves):
            return None, None, "empty"

        # Cache results
        if self.cache:
            cache_data = json.dumps({"implied": implied_moves, "actual": actual_moves})
            self.cache.write(cache_key, cache_data)

        win_rate, avg_profit = self._calculate_stats(implied_moves, actual_moves)
        return win_rate, avg_profit, "ok"

    def _scrape_earnings_data(self, ticker: str) -> Tuple[list, list]:
        """Scrape earnings data using Playwright."""
        url = UNUSUAL_WHALES_URL.format(ticker=ticker)
        implied_moves = []
        actual_moves = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()

                try:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    page.wait_for_selector("table", timeout=15000)
                    time.sleep(2)  # Wait for data to populate

                    # Find the earnings table
                    tables = page.query_selector_all("table")

                    for table in tables:
                        thead = table.query_selector("thead")
                        if not thead:
                            continue

                        # Get headers
                        header_cells = thead.query_selector_all("th, td")
                        headers = [self._normalize_header(h.inner_text()) for h in header_cells]

                        # Look for relevant columns
                        implied_idx = None
                        actual_idx = None

                        for i, h in enumerate(headers):
                            if "implied move" in h:
                                implied_idx = i
                            elif h == "1d move":
                                actual_idx = i

                        if implied_idx is None or actual_idx is None:
                            continue

                        # Extract data
                        tbody = table.query_selector("tbody")
                        if not tbody:
                            continue

                        rows = tbody.query_selector_all("tr")
                        for row in rows:
                            cells = row.query_selector_all("td, th")
                            if len(cells) <= max(implied_idx, actual_idx):
                                continue

                            implied_text = cells[implied_idx].inner_text()
                            actual_text = cells[actual_idx].inner_text()

                            implied_val = self._parse_percentage(implied_text)
                            actual_val = self._parse_percentage(actual_text)

                            if implied_val is not None and actual_val is not None:
                                implied_moves.append(implied_val)
                                actual_moves.append(actual_val)

                        break  # Found the right table

                except PlaywrightTimeout:
                    self.logger.debug(f"{ticker}: Playwright timeout")
                finally:
                    context.close()
                    browser.close()

        except Exception as exc:
            self.logger.debug(f"{ticker}: Playwright error - {exc}")

        return implied_moves, actual_moves

    @staticmethod
    def _calculate_stats(implied: list, actual: list) -> Tuple[float, float]:
        """Calculate win rate and average profit."""
        wins = 0
        profits = []

        for imp, act in zip(implied, actual):
            actual_abs = abs(act)
            profit = imp - actual_abs
            profits.append(profit)

            if actual_abs < imp:
                wins += 1

        win_rate = (wins / len(implied)) * 100.0
        avg_profit = float(np.mean(profits))

        return win_rate, avg_profit

    @staticmethod
    def _normalize_header(text: str) -> str:
        """Normalize header text."""
        return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip().lower()

    @staticmethod
    def _parse_percentage(text: str) -> Optional[float]:
        """Parse percentage value from text."""
        if not text:
            return None

        cleaned = text.strip().lower()
        if not cleaned or cleaned in {"", "-", "—", "–", "n/a", "na"}:
            return None

        # Handle parentheses (negative values)
        negative = False
        if "(" in cleaned and ")" in cleaned:
            negative = True
            cleaned = cleaned.replace("(", "").replace(")", "")

        # Extract from multiline if needed
        if "%" in cleaned:
            for part in cleaned.splitlines():
                if "%" in part:
                    cleaned = part.strip()
                    break

        # Remove formatting
        cleaned = cleaned.replace(",", "").replace("%", "")

        # Extract number
        pattern = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
        match = pattern.search(cleaned)

        if not match:
            return None

        value = float(match.group())
        if negative and value >= 0:
            value = -value

        return value
