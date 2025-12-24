"""Data models for screening results."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TradeQuality(Enum):
    """Trade quality classification."""
    PREMIUM = "premium"
    QUALITY = "quality"
    STANDARD = "standard"
    SKIP = "skip"


@dataclass
class TickerAnalysis:
    """Analysis results for a single ticker."""

    ticker: str
    iv_rv_ratio: Optional[float]
    term_slope: Optional[float]
    avg_volume: Optional[float]
    expected_move: Optional[float]
    uw_win_rate: Optional[float]
    uw_avg_profit: Optional[float]
    quality: TradeQuality

    @property
    def is_tradeable(self) -> bool:
        """Check if this ticker represents a tradeable opportunity."""
        return self.quality in (TradeQuality.PREMIUM, TradeQuality.QUALITY, TradeQuality.STANDARD)


@dataclass
class ScreenResult:
    """Complete screening results."""

    date: str
    total_analyzed: int
    premium_setups: list[TickerAnalysis]
    quality_setups: list[TickerAnalysis]
    standard_setups: list[TickerAnalysis]
    skipped: list[str]
    errors: list[str]

    @property
    def total_opportunities(self) -> int:
        """Total number of tradeable opportunities."""
        return len(self.premium_setups) + len(self.quality_setups) + len(self.standard_setups)
