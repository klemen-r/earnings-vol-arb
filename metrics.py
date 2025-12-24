from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.interpolate import interp1d

AVG_VOLUME_MIN = 1_500_000
IVRV_MIN = 1.25
TS_SLOPE_MAX = -0.00406


class MetricsError(Exception):
    """Raised when calculator metrics cannot be computed."""


def filter_dates(dates: Iterable[str]) -> List[str]:
    today = datetime.today().date()
    cutoff_date = today + timedelta(days=45)

    sorted_dates = sorted(datetime.strptime(date, "%Y-%m-%d").date() for date in dates)

    arr: List[str] = []
    for i, date in enumerate(sorted_dates):
        if date >= cutoff_date:
            arr = [d.strftime("%Y-%m-%d") for d in sorted_dates[: i + 1]]
            break

    if arr:
        if arr[0] == today.strftime("%Y-%m-%d"):
            return arr[1:]
        return arr

    raise ValueError("No date 45 days or more in the future found.")


def yang_zhang(
    price_data: pd.DataFrame,
    window: int = 30,
    trading_periods: int = 252,
    return_last_only: bool = True,
):
    log_ho = (price_data["High"] / price_data["Open"]).apply(np.log)
    log_lo = (price_data["Low"] / price_data["Open"]).apply(np.log)
    log_co = (price_data["Close"] / price_data["Open"]).apply(np.log)

    log_oc = (price_data["Open"] / price_data["Close"].shift(1)).apply(np.log)
    log_oc_sq = log_oc**2

    log_cc = (price_data["Close"] / price_data["Close"].shift(1)).apply(np.log)
    log_cc_sq = log_cc**2

    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

    close_vol = log_cc_sq.rolling(window=window, center=False).sum() * (
        1.0 / (window - 1.0)
    )

    open_vol = log_oc_sq.rolling(window=window, center=False).sum() * (
        1.0 / (window - 1.0)
    )

    window_rs = rs.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))

    k = 0.34 / (1.34 + ((window + 1) / (window - 1)))
    result = (open_vol + k * close_vol + (1 - k) * window_rs).apply(np.sqrt) * np.sqrt(
        trading_periods
    )

    if return_last_only:
        return result.iloc[-1]
    return result.dropna()


def build_term_structure(days: Iterable[int], ivs: Iterable[float]):
    days = np.array(days)
    ivs = np.array(ivs)

    sort_idx = days.argsort()
    days = days[sort_idx]
    ivs = ivs[sort_idx]

    mask = np.isfinite(days) & np.isfinite(ivs)
    days = days[mask]
    ivs = ivs[mask]

    unique_days, unique_idx = np.unique(days, return_index=True)
    days = unique_days
    ivs = ivs[unique_idx]

    if len(days) < 3:
        raise ValueError("Insufficient term structure data")

    with np.errstate(divide="ignore", invalid="ignore"):
        spline = interp1d(days, ivs, kind="linear", fill_value="extrapolate")

    def term_spline(dte: int) -> float:
        if dte < days[0]:
            return float(ivs[0])
        if dte > days[-1]:
            return float(ivs[-1])
        return float(spline(dte))

    return term_spline


def get_current_price(ticker: yf.Ticker) -> float:
    todays_data = ticker.history(period="1d")
    return float(todays_data["Close"].iloc[0])


def compute_base_metrics(
    ticker: str, stock_obj: Optional[yf.Ticker] = None
) -> Dict[str, Optional[float]]:
    symbol = ticker.strip().upper()
    if not symbol:
        raise MetricsError("Ticker symbol is empty.")

    stock = stock_obj or yf.Ticker(symbol)
    option_dates = list(stock.options)
    if not option_dates:
        raise MetricsError("No options expirations available.")

    try:
        filtered_expirations = filter_dates(option_dates)
    except Exception as exc:
        raise MetricsError(f"Insufficient option expirations: {exc}") from exc

    chains = {}
    for expiry in filtered_expirations:
        try:
            chains[expiry] = stock.option_chain(expiry)
        except Exception as exc:
            raise MetricsError(
                f"Failed to download option chain for {expiry}: {exc}"
            ) from exc

    try:
        underlying_price = get_current_price(stock)
    except Exception:
        underlying_price = None

    if underlying_price is None:
        raise MetricsError("Unable to determine underlying price.")

    atm_iv: Dict[str, float] = {}
    straddle_cost = None
    for index, (expiry, chain) in enumerate(chains.items()):
        calls = chain.calls
        puts = chain.puts
        if calls is None or puts is None or calls.empty or puts.empty:
            continue

        call_idx = (calls["strike"] - underlying_price).abs().idxmin()
        put_idx = (puts["strike"] - underlying_price).abs().idxmin()

        call_iv = calls.loc[call_idx, "impliedVolatility"]
        put_iv = puts.loc[put_idx, "impliedVolatility"]
        if pd.isna(call_iv) or pd.isna(put_iv):
            continue

        atm_iv[expiry] = float((call_iv + put_iv) / 2.0)

        if index == 0:
            call_bid = calls.loc[call_idx, "bid"]
            call_ask = calls.loc[call_idx, "ask"]
            put_bid = puts.loc[put_idx, "bid"]
            put_ask = puts.loc[put_idx, "ask"]
            if (
                pd.notna(call_bid)
                and pd.notna(call_ask)
                and pd.notna(put_bid)
                and pd.notna(put_ask)
            ):
                call_mid = (call_bid + call_ask) / 2.0
                put_mid = (put_bid + put_ask) / 2.0
                straddle_cost = float(call_mid + put_mid)

    if not atm_iv:
        raise MetricsError("Unable to compute ATM implied volatility curve.")

    today = datetime.today().date()
    dtes: List[int] = []
    ivs: List[float] = []
    for expiry, iv in atm_iv.items():
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        days = (expiry_date - today).days
        if days <= 0:
            continue
        dtes.append(days)
        ivs.append(iv)

    if not dtes:
        raise MetricsError("Option expirations are all in the past.")

    try:
        term_spline = build_term_structure(dtes, ivs)
    except ValueError as exc:
        raise MetricsError(f"Term structure failed ({exc})") from exc
    denominator = 45 - dtes[0]
    ts_slope = 0.0
    if denominator != 0:
        ts_slope = (float(term_spline(45)) - float(term_spline(dtes[0]))) / denominator

    price_history = stock.history(period="3mo")
    if price_history.empty:
        raise MetricsError("Price history unavailable.")

    rv30 = yang_zhang(price_history)
    if rv30 == 0 or pd.isna(rv30):
        raise MetricsError("Realized volatility calculation failed.")

    iv30 = float(term_spline(30))
    iv_rv_ratio = iv30 / float(rv30)

    avg_volume_series = price_history["Volume"].rolling(30).mean().dropna()
    if avg_volume_series.empty:
        raise MetricsError("Average volume calculation failed.")
    avg_volume = float(avg_volume_series.iloc[-1])

    avg_volume_ok = avg_volume >= AVG_VOLUME_MIN
    iv_rv_ok = iv_rv_ratio >= IVRV_MIN
    ts_slope_ok = ts_slope <= TS_SLOPE_MAX

    expected_move = None
    if straddle_cost and underlying_price:
        expected_move = (straddle_cost / underlying_price) * 100.0

    return {
        "ticker": symbol,
        "iv_rv_ratio": iv_rv_ratio,
        "ts_slope": ts_slope,
        "avg_volume": avg_volume,
        "expected_move": expected_move,
        "avg_volume_ok": avg_volume_ok,
        "iv_rv_ok": iv_rv_ok,
        "ts_slope_ok": ts_slope_ok,
    }
