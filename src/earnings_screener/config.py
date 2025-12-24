"""
Configuration settings for the earnings screener.
Centralized config makes it easy to tweak things without digging through code.
"""

from dataclasses import dataclass
from pathlib import Path

# API endpoints and URLs
NASDAQ_API_URL = "https://api.nasdaq.com/api/calendar/earnings"
UNUSUAL_WHALES_URL = "https://unusualwhales.com/stock/{ticker}/earnings"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

# Network Configuration
MAX_RETRIES = 5
REQUEST_TIMEOUT = 20
BACKOFF_BASE = 1.6
DEFAULT_WORKERS = 8
DEFAULT_RPS = 1.0

# Cache Configuration
CACHE_ROOT = Path(".cache") / "earnings_screener"

# Timezone Configuration
TIMEZONE_LOCAL = "Europe/Ljubljana"
TIMEZONE_NY = "America/New_York"

# Calendar Configuration
CALENDAR_NAMES = ("XNAS", "NASDAQ", "XNYS")

# Internal thresholds - these work well but you can adjust if needed
_AVG_VOLUME_MIN = 1_500_000  # minimum daily volume for liquidity
_IVRV_MIN = 1.25  # IV should be at least 25% above RV
_TS_SLOPE_MAX = -0.00406  # term structure slope indicating front-month elevation


@dataclass
class ScreenerConfig:
    """Configuration for screener execution."""

    workers: int = DEFAULT_WORKERS
    rps: float = DEFAULT_RPS
    cache_enabled: bool = False
    include_uw_stats: bool = True
    log_level: str = "info"

    def __post_init__(self):
        """Validate configuration."""
        if self.workers < 1:
            self.workers = 1
        if self.rps < 0:
            self.rps = 0.1


# Brand colors for output
class Colors:
    """Colors used for terminal output."""
    PRIMARY = "#0066FF"
    SUCCESS = "#00C853"
    WARNING = "#FFB300"
    DANGER = "#E53935"
    INFO = "#26C6DA"
    MUTED = "#78909C"
