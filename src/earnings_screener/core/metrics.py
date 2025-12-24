"""Options metrics: implied and realized volatility, term structure, liquidity."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.interpolate import interp1d

from ..config import _AVG_VOLUME_MIN, _IVRV_MIN, _TS_SLOPE_MAX
from .models import TradeQuality


class MetricsError(Exception):
    """Raised when we can't calculate metrics (usually missing data)."""
    pass


class MetricsCalculator:
    """Calculate options metrics for ticker analysis."""

    @staticmethod
    def calculate(ticker: str, stock_obj: Optional[yf.Ticker] = None) -> Dict:
        """
        Calculate all metrics for a ticker.

        Args:
            ticker: Stock symbol
            stock_obj: Optional pre-loaded yfinance Ticker object

        Returns:
            Dictionary containing calculated metrics

        Raises:
            MetricsError: If metrics cannot be calculated
        """
        symbol = ticker.strip().upper()
        stock = stock_obj or yf.Ticker(symbol)

        # Get options expirations
        option_dates = list(stock.options)
        if not option_dates:
            raise MetricsError("No options available")

        # Filter to relevant expirations
        filtered_expirations = MetricsCalculator._filter_expirations(option_dates)
        if not filtered_expirations:
            raise MetricsError("Insufficient option expirations")

        # Get underlying price
        underlying_price = MetricsCalculator._get_current_price(stock)
        if underlying_price is None:
            raise MetricsError("Unable to determine stock price")

        # Calculate IV term structure
        atm_iv_by_expiry, straddle_cost = MetricsCalculator._calculate_atm_iv(
            stock, filtered_expirations, underlying_price
        )

        if not atm_iv_by_expiry:
            raise MetricsError("Unable to calculate implied volatility")

        # Build term structure
        today = datetime.today().date()
        dtes = []
        ivs = []

        for expiry, iv in atm_iv_by_expiry.items():
            expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            days = (expiry_date - today).days
            if days > 0:
                dtes.append(days)
                ivs.append(iv)

        if not dtes:
            raise MetricsError("No valid expirations")

        term_spline = MetricsCalculator._build_term_structure(dtes, ivs)

        # Calculate term structure slope
        denominator = 45 - dtes[0]
        ts_slope = 0.0
        if denominator != 0:
            ts_slope = (float(term_spline(45)) - float(term_spline(dtes[0]))) / denominator

        # Calculate realized volatility
        price_history = stock.history(period="3mo")
        if price_history.empty:
            raise MetricsError("Price history unavailable")

        rv30 = MetricsCalculator._yang_zhang_volatility(price_history)
        if rv30 == 0 or pd.isna(rv30):
            raise MetricsError("Cannot calculate realized volatility")

        iv30 = float(term_spline(30))
        iv_rv_ratio = iv30 / float(rv30)

        # Calculate average volume
        avg_volume_series = price_history["Volume"].rolling(30).mean().dropna()
        if avg_volume_series.empty:
            raise MetricsError("Cannot calculate average volume")
        avg_volume = float(avg_volume_series.iloc[-1])

        # Calculate expected move
        expected_move = None
        if straddle_cost and underlying_price:
            expected_move = (straddle_cost / underlying_price) * 100.0

        # Determine quality (internal logic)
        quality = MetricsCalculator._classify_quality(
            avg_volume >= _AVG_VOLUME_MIN,
            iv_rv_ratio >= _IVRV_MIN,
            ts_slope <= _TS_SLOPE_MAX
        )

        return {
            "ticker": symbol,
            "iv_rv_ratio": iv_rv_ratio,
            "ts_slope": ts_slope,
            "avg_volume": avg_volume,
            "expected_move": expected_move,
            "quality": quality,
        }

    @staticmethod
    def _filter_expirations(dates: List[str]) -> List[str]:
        """Filter expirations to relevant dates (up to 45 DTE)."""
        today = datetime.today().date()
        cutoff_date = today + timedelta(days=45)

        sorted_dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)

        result = []
        for i, date in enumerate(sorted_dates):
            if date >= cutoff_date:
                result = [d.strftime("%Y-%m-%d") for d in sorted_dates[: i + 1]]
                break

        if result and result[0] == today.strftime("%Y-%m-%d"):
            return result[1:]
        return result

    @staticmethod
    def _get_current_price(ticker: yf.Ticker) -> Optional[float]:
        """Get current stock price."""
        try:
            todays_data = ticker.history(period="1d")
            return float(todays_data["Close"].iloc[0])
        except Exception:
            return None

    @staticmethod
    def _calculate_atm_iv(
        stock: yf.Ticker,
        expirations: List[str],
        underlying_price: float
    ) -> tuple[Dict[str, float], Optional[float]]:
        """Calculate ATM IV for each expiration."""
        atm_iv = {}
        straddle_cost = None

        for idx, expiry in enumerate(expirations):
            try:
                chain = stock.option_chain(expiry)
                calls = chain.calls
                puts = chain.puts

                if calls is None or puts is None or calls.empty or puts.empty:
                    continue

                # Find ATM strike
                call_idx = (calls["strike"] - underlying_price).abs().idxmin()
                put_idx = (puts["strike"] - underlying_price).abs().idxmin()

                call_iv = calls.loc[call_idx, "impliedVolatility"]
                put_iv = puts.loc[put_idx, "impliedVolatility"]

                if pd.isna(call_iv) or pd.isna(put_iv):
                    continue

                atm_iv[expiry] = float((call_iv + put_iv) / 2.0)

                # Calculate front-month straddle cost
                if idx == 0:
                    call_bid = calls.loc[call_idx, "bid"]
                    call_ask = calls.loc[call_idx, "ask"]
                    put_bid = puts.loc[put_idx, "bid"]
                    put_ask = puts.loc[put_idx, "ask"]

                    if all(pd.notna(x) for x in [call_bid, call_ask, put_bid, put_ask]):
                        call_mid = (call_bid + call_ask) / 2.0
                        put_mid = (put_bid + put_ask) / 2.0
                        straddle_cost = float(call_mid + put_mid)

            except Exception:
                continue

        return atm_iv, straddle_cost

    @staticmethod
    def _build_term_structure(days: List[int], ivs: List[float]):
        """Build IV term structure interpolator."""
        days_arr = np.array(days)
        ivs_arr = np.array(ivs)

        sort_idx = days_arr.argsort()
        days_arr = days_arr[sort_idx]
        ivs_arr = ivs_arr[sort_idx]

        mask = np.isfinite(days_arr) & np.isfinite(ivs_arr)
        days_arr = days_arr[mask]
        ivs_arr = ivs_arr[mask]

        unique_days, unique_idx = np.unique(days_arr, return_index=True)
        days_arr = unique_days
        ivs_arr = ivs_arr[unique_idx]

        if len(days_arr) < 3:
            raise ValueError("Insufficient term structure data")

        with np.errstate(divide="ignore", invalid="ignore"):
            spline = interp1d(days_arr, ivs_arr, kind="linear", fill_value="extrapolate")

        def term_spline(dte: int) -> float:
            if dte < days_arr[0]:
                return float(ivs_arr[0])
            if dte > days_arr[-1]:
                return float(ivs_arr[-1])
            return float(spline(dte))

        return term_spline

    @staticmethod
    def _yang_zhang_volatility(
        price_data: pd.DataFrame,
        window: int = 30,
        trading_periods: int = 252,
    ) -> float:
        """Calculate Yang-Zhang realized volatility."""
        log_ho = (price_data["High"] / price_data["Open"]).apply(np.log)
        log_lo = (price_data["Low"] / price_data["Open"]).apply(np.log)
        log_co = (price_data["Close"] / price_data["Open"]).apply(np.log)

        log_oc = (price_data["Open"] / price_data["Close"].shift(1)).apply(np.log)
        log_oc_sq = log_oc ** 2

        log_cc = (price_data["Close"] / price_data["Close"].shift(1)).apply(np.log)
        log_cc_sq = log_cc ** 2

        rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

        close_vol = log_cc_sq.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
        open_vol = log_oc_sq.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))
        window_rs = rs.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))

        k = 0.34 / (1.34 + ((window + 1) / (window - 1)))
        result = (open_vol + k * close_vol + (1 - k) * window_rs).apply(np.sqrt) * np.sqrt(trading_periods)

        return result.iloc[-1]

    @staticmethod
    def _classify_quality(avg_volume_ok: bool, iv_rv_ok: bool, ts_slope_ok: bool) -> TradeQuality:
        """Classify trade quality based on metrics."""
        if avg_volume_ok and iv_rv_ok and ts_slope_ok:
            return TradeQuality.PREMIUM
        elif ts_slope_ok and ((avg_volume_ok and not iv_rv_ok) or (iv_rv_ok and not avg_volume_ok)):
            return TradeQuality.QUALITY
        elif ts_slope_ok:
            return TradeQuality.STANDARD
        return TradeQuality.SKIP
