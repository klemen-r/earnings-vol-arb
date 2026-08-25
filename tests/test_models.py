"""Tests for the screening result models."""

import pytest

from earnings_screener.core.models import ScreenResult, TickerAnalysis, TradeQuality


def _analysis(ticker: str, quality: TradeQuality) -> TickerAnalysis:
    return TickerAnalysis(
        ticker=ticker,
        iv_rv_ratio=1.4,
        term_slope=-0.006,
        avg_volume=2_000_000,
        expected_move=0.05,
        uw_win_rate=None,
        uw_avg_profit=None,
        quality=quality,
    )


@pytest.mark.parametrize(
    "quality",
    [TradeQuality.PREMIUM, TradeQuality.QUALITY, TradeQuality.STANDARD],
)
def test_classified_setups_are_tradeable(quality):
    assert _analysis("AAPL", quality).is_tradeable is True


def test_skipped_setups_are_not_tradeable():
    assert _analysis("AAPL", TradeQuality.SKIP).is_tradeable is False


def test_total_opportunities_counts_every_tradeable_tier():
    result = ScreenResult(
        date="2026-01-15",
        total_analyzed=6,
        premium_setups=[_analysis("AAPL", TradeQuality.PREMIUM)],
        quality_setups=[
            _analysis("MSFT", TradeQuality.QUALITY),
            _analysis("GOOGL", TradeQuality.QUALITY),
        ],
        standard_setups=[_analysis("AMZN", TradeQuality.STANDARD)],
        skipped=["TSLA"],
        errors=["NVDA: no options"],
    )

    assert result.total_opportunities == 4


def test_total_opportunities_is_zero_without_setups():
    result = ScreenResult(
        date="2026-01-15",
        total_analyzed=2,
        premium_setups=[],
        quality_setups=[],
        standard_setups=[],
        skipped=["TSLA", "NVDA"],
        errors=[],
    )

    assert result.total_opportunities == 0
