"""Tests for the pure metric helpers in earnings_screener.core.metrics."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from earnings_screener.core.metrics import MetricsCalculator
from earnings_screener.core.models import TradeQuality


def _iso(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).strftime("%Y-%m-%d")


class TestFilterExpirations:
    def test_keeps_expirations_up_to_the_first_one_past_the_cutoff(self):
        dates = [_iso(7), _iso(14), _iso(30), _iso(50), _iso(90)]

        result = MetricsCalculator._filter_expirations(dates)

        assert result == [_iso(7), _iso(14), _iso(30), _iso(50)]

    def test_sorts_unordered_input(self):
        dates = [_iso(50), _iso(7), _iso(30)]

        assert MetricsCalculator._filter_expirations(dates) == [_iso(7), _iso(30), _iso(50)]

    def test_drops_an_expiration_dated_today(self):
        dates = [_iso(0), _iso(10), _iso(60)]

        result = MetricsCalculator._filter_expirations(dates)

        assert _iso(0) not in result
        assert result == [_iso(10), _iso(60)]

    def test_returns_empty_when_nothing_reaches_the_cutoff(self):
        # Every expiration is inside 45 DTE, so no term structure can be built.
        assert MetricsCalculator._filter_expirations([_iso(7), _iso(14)]) == []


class TestBuildTermStructure:
    def test_interpolates_between_known_points(self):
        spline = MetricsCalculator._build_term_structure([7, 30, 60], [0.50, 0.40, 0.35])

        assert spline(7) == pytest.approx(0.50)
        assert spline(30) == pytest.approx(0.40)
        assert 0.35 < spline(45) < 0.40

    def test_clamps_outside_the_observed_range(self):
        spline = MetricsCalculator._build_term_structure([7, 30, 60], [0.50, 0.40, 0.35])

        assert spline(1) == pytest.approx(0.50)
        assert spline(365) == pytest.approx(0.35)

    def test_deduplicates_repeated_maturities(self):
        spline = MetricsCalculator._build_term_structure([7, 7, 30, 60], [0.50, 0.55, 0.40, 0.35])

        assert spline(30) == pytest.approx(0.40)

    def test_rejects_too_few_points(self):
        with pytest.raises(ValueError):
            MetricsCalculator._build_term_structure([7, 30], [0.5, 0.4])


class TestYangZhangVolatility:
    @staticmethod
    def _frame(rows: int, price: float = 100.0) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Open": [price] * rows,
                "High": [price] * rows,
                "Low": [price] * rows,
                "Close": [price] * rows,
            }
        )

    def test_flat_prices_have_no_realized_volatility(self):
        result = MetricsCalculator._yang_zhang_volatility(self._frame(40))

        assert result == pytest.approx(0.0, abs=1e-12)

    def test_moving_prices_produce_positive_volatility(self):
        rng = np.random.default_rng(7)
        closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 60)))
        frame = pd.DataFrame(
            {
                "Open": closes,
                "High": closes * 1.005,
                "Low": closes * 0.995,
                "Close": closes,
            }
        )

        assert MetricsCalculator._yang_zhang_volatility(frame) > 0

    def test_returns_nan_when_the_window_is_not_filled(self):
        assert np.isnan(MetricsCalculator._yang_zhang_volatility(self._frame(10)))


class TestClassifyQuality:
    def test_all_criteria_met_is_premium(self):
        assert MetricsCalculator._classify_quality(True, True, True) is TradeQuality.PREMIUM

    @pytest.mark.parametrize(
        "avg_volume_ok, iv_rv_ok",
        [(True, False), (False, True)],
    )
    def test_slope_plus_exactly_one_other_criterion_is_quality(self, avg_volume_ok, iv_rv_ok):
        result = MetricsCalculator._classify_quality(avg_volume_ok, iv_rv_ok, True)

        assert result is TradeQuality.QUALITY

    def test_slope_alone_is_standard(self):
        assert MetricsCalculator._classify_quality(False, False, True) is TradeQuality.STANDARD

    @pytest.mark.parametrize(
        "avg_volume_ok, iv_rv_ok",
        [(True, True), (True, False), (False, False)],
    )
    def test_without_the_slope_criterion_the_setup_is_skipped(self, avg_volume_ok, iv_rv_ok):
        result = MetricsCalculator._classify_quality(avg_volume_ok, iv_rv_ok, False)

        assert result is TradeQuality.SKIP
