#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import random
import re
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf
from bs4 import BeautifulSoup

# optional styling libs
try:
    from rich.console import Console
    from rich.table import Table
except Exception:
    Console = None
    Table = None

try:
    from tabulate import tabulate
except Exception:
    tabulate = None

try:
    import pandas_market_calendars as mcal  # type: ignore
except ImportError:  # pragma: no cover
    mcal = None

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    PlaywrightTimeout = Exception

from metrics import (
    AVG_VOLUME_MIN,
    IVRV_MIN,
    TS_SLOPE_MAX,
    MetricsError,
    compute_base_metrics,
)

NASDAQ_CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings"
UNUSUAL_WHALES_URL_TEMPLATE = "https://unusualwhales.com/stock/{ticker}/earnings"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
MAX_FETCH_TRIES = 5
FETCH_TIMEOUT = 20
BACKOFF_BASE = 1.6
DEFAULT_WORKERS = 3
DEFAULT_RPS = 0.5
CACHE_ROOT = Path(".cache") / "earnings_filter"
TZ_LJUBLJANA = pytz.timezone("Europe/Ljubljana")
TZ_NEW_YORK = pytz.timezone("America/New_York")
CALENDAR_NAMES = ("XNAS", "NASDAQ", "XNYS")
PCT_EMPTY_TOKENS = {"", "-", "\u2014", "\u2013", "n/a", "na"}
PCT_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
RECOMMENDED_COLUMNS = [
    "ticker",
    "iv_rv_ratio",
    "ts_slope",
    "avg_volume",
    "uw_win_rate",
    "uw_avg_excess",
]
ALL_COLUMNS = RECOMMENDED_COLUMNS + ["recommendation"]


LOG = logging.getLogger(__name__)


@dataclass
class TickerResult:
    ticker: str
    iv_rv_ratio: Optional[float]
    ts_slope: Optional[float]
    avg_volume: Optional[float]
    classification: Optional[str]
    uw_win_rate: Optional[float]
    uw_avg_excess: Optional[float]


@dataclass
class TaskOutcome:
    result: TickerResult
    metrics_status: str
    uw_status: str
    errors: List[str]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter earnings tickers using calculator metrics."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {resolve_version()}",
    )
    parser.add_argument("--date", help="Override target earnings date (YYYY-MM-DD).")
    parser.add_argument("--tickers", help="Fallback comma-separated ticker list.")
    parser.add_argument(
        "--out", default="recommended_report.csv", help="Recommended CSV output path."
    )
    parser.add_argument(
        "--save-all", dest="save_all", help="Optional CSV path for all tickers."
    )
    parser.add_argument(
        "--style",
        choices=["csv", "table", "md", "json"],
        default="csv",
        help="Output style.",
    )
    parser.add_argument(
        "--no-uw", action="store_true", help="Skip UnusualWhales scraping."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Max concurrent ticker tasks.",
    )
    parser.add_argument(
        "--rps", type=float, default=DEFAULT_RPS, help="Global requests-per-second cap."
    )
    parser.add_argument(
        "--cache", action="store_true", help="Enable on-disk HTML caching."
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
        help="Logging verbosity.",
    )
    return parser.parse_args(argv)


def resolve_version() -> str:
    try:
        return importlib_metadata.version("earnings-filter")
    except importlib_metadata.PackageNotFoundError:
        return "dev"


def setup_logging(level_name: str) -> logging.Logger:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")
    return logging.getLogger("earnings_filter")


class RateLimiter:
    def __init__(self, rate_per_sec: float):
        self.rate_per_sec = max(rate_per_sec, 0.0)
        self.min_interval = 1.0 / self.rate_per_sec if self.rate_per_sec > 0 else 0.0
        self.lock = threading.Lock()
        self.next_time = 0.0

    def acquire(self) -> None:
        # gate outbound requests
        if self.min_interval <= 0:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                if now >= self.next_time:
                    self.next_time = now + self.min_interval
                    return
                wait = self.next_time - now
            time.sleep(wait)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def sanitize_slug(slug: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", slug)


def cache_read(base_dir: Path, slug: str) -> Optional[str]:
    path = base_dir / f"{sanitize_slug(slug)}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def cache_write(base_dir: Path, slug: str, content: str) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{sanitize_slug(slug)}.html"
    path.write_text(content, encoding="utf-8")


def fetch_with_backoff(
    session: requests.Session,
    url: str,
    limiter: Optional[RateLimiter],
    logger: logging.Logger,
) -> str:
    attempt = 0
    while attempt < MAX_FETCH_TRIES:
        attempt += 1
        if limiter:
            limiter.acquire()
        try:
            response = session.get(url, timeout=FETCH_TIMEOUT)
        except requests.RequestException as exc:
            # retry on transport error
            logger.debug("Request error on %s: %s", url, exc)
            if attempt == MAX_FETCH_TRIES:
                raise RuntimeError(
                    f"{url}: request failed after retries ({exc})"
                ) from exc
            sleep = BACKOFF_BASE**attempt + random.uniform(0.2, 0.8)
            time.sleep(sleep)
            continue

        status = response.status_code
        if status == 200:
            text = response.text
            time.sleep(random.uniform(0.3, 0.7))
            return text

        if status in (429,) or 500 <= status < 600:
            # retry on saturated backend
            sleep = BACKOFF_BASE**attempt + random.uniform(0.2, 0.8)
            logger.debug("HTTP %s on %s; retrying after %.2fs", status, url, sleep)
            time.sleep(sleep)
            continue

        raise RuntimeError(f"{url}: unexpected HTTP status {status}")

    raise RuntimeError(f"{url}: failed after {MAX_FETCH_TRIES} attempts")


class HttpClient:
    def __init__(
        self,
        limiter: Optional[RateLimiter],
        cache_dir: Optional[Path],
        logger: logging.Logger,
    ):
        self.limiter = limiter
        self.cache_dir = cache_dir
        self.logger = logger
        self._local = threading.local()

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = make_session()
        return self._local.session

    def get(self, url: str, cache_key: Optional[str] = None) -> str:
        if self.cache_dir and cache_key:
            cached = cache_read(self.cache_dir, cache_key)
            if cached is not None:
                self.logger.debug("Cache hit for %s", cache_key)
                return cached

        text = fetch_with_backoff(self._session(), url, self.limiter, self.logger)

        if self.cache_dir and cache_key:
            # stash raw html for reuse
            cache_write(self.cache_dir, cache_key, text)
        return text


def normalize_header(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip().lower()


def parse_pct(text: str) -> Optional[float]:
    if text is None:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in PCT_EMPTY_TOKENS:
        return None

    candidate = cleaned
    if "%" in cleaned:
        for part in cleaned.splitlines():
            if "%" in part:
                candidate = part.strip()
                break

    if not candidate:
        return None
    lowered_candidate = candidate.lower()
    if lowered_candidate in PCT_EMPTY_TOKENS:
        return None

    negative = False
    if "(" in candidate and ")" in candidate:
        negative = True
        candidate = candidate.replace("(", "").replace(")", "")

    candidate = candidate.replace(",", "").replace("%", "")
    match = PCT_PATTERN.search(candidate)
    if not match:
        return None

    value = float(match.group())
    if negative and value >= 0:
        value = -value
    return value if candidate.strip() else None


def compute_implied_vs_actual_stats(
    implied_moves: List[float],
    actual_moves: List[float],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calculate win rate and average excess for short straddle strategy.

    Win rate: percentage of times |actual_move| < implied_move (straddle seller wins)
    Avg excess: average of (implied_move - |actual_move|) as percentage points
    """
    if not implied_moves or not actual_moves or len(implied_moves) != len(actual_moves):
        return None, None

    wins = 0
    excess_values = []

    for implied, actual in zip(implied_moves, actual_moves):
        actual_abs = abs(actual)
        excess = implied - actual_abs
        excess_values.append(excess)
        if actual_abs < implied:
            wins += 1

    win_rate = (wins / len(implied_moves)) * 100.0
    avg_excess = float(np.mean(excess_values))
    return win_rate, avg_excess


def extract_earnings_moves_playwright(
    ticker: str,
    cache_dir: Optional[Path],
    logger: logging.Logger,
) -> Tuple[bool, List[float], List[float]]:
    """
    Use Playwright to render the UnusualWhales earnings page and extract
    Implied Move and 1d Move columns from the Historical Earnings Data table.

    Returns: (found, implied_moves, actual_1d_moves)
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning(
            "Playwright not available - install with: pip install playwright && playwright install chromium"
        )
        return False, [], []

    url = UNUSUAL_WHALES_URL_TEMPLATE.format(ticker=ticker)
    cache_key = f"uw_{ticker}"

    # Check cache first
    if cache_dir:
        cached = cache_read(cache_dir, cache_key)
        if cached:
            try:
                data = json.loads(cached)
                return True, data.get("implied", []), data.get("actual", [])
            except json.JSONDecodeError:
                pass

    implied_moves: List[float] = []
    actual_moves: List[float] = []

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
                # Wait for the table to appear
                page.wait_for_selector("table", timeout=15000)
                # Extra wait for data to populate
                time.sleep(2)

                # Find all tables and look for the Historical Earnings Data table
                tables = page.query_selector_all("table")

                for table in tables:
                    # Get headers
                    thead = table.query_selector("thead")
                    if not thead:
                        continue

                    header_cells = thead.query_selector_all("th, td")
                    headers = [normalize_header(h.inner_text()) for h in header_cells]

                    # Look for Implied Move and 1d Move columns
                    implied_idx = None
                    actual_idx = None

                    for i, h in enumerate(headers):
                        if "implied move" in h:
                            implied_idx = i
                        elif h == "1d move":
                            actual_idx = i

                    if implied_idx is None or actual_idx is None:
                        continue

                    # Found the right table - extract data
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

                        implied_val = parse_pct(implied_text)
                        actual_val = parse_pct(actual_text)

                        if implied_val is not None and actual_val is not None:
                            implied_moves.append(implied_val)
                            actual_moves.append(actual_val)

                    break  # Found and processed the table

            except PlaywrightTimeout:
                logger.debug(f"{ticker}: Playwright timeout waiting for table")
            finally:
                context.close()
                browser.close()

    except Exception as exc:
        logger.debug(f"{ticker}: Playwright error - {exc}")
        return False, [], []

    # Cache the extracted data as JSON
    if cache_dir and implied_moves:
        cache_data = json.dumps({"implied": implied_moves, "actual": actual_moves})
        cache_write(cache_dir, cache_key, cache_data)

    found = len(implied_moves) > 0
    return found, implied_moves, actual_moves


def fetch_unusual_whales_stats(
    ticker: str,
    cache_dir: Optional[Path],
    logger: logging.Logger,
) -> Tuple[Optional[float], Optional[float], Optional[str], str]:
    """
    Fetch earnings data from UnusualWhales and calculate win rate.

    Win rate = % of times |1d Move| < Implied Move
    Avg excess = average of (Implied Move - |1d Move|)
    """
    found, implied_moves, actual_moves = extract_earnings_moves_playwright(
        ticker, cache_dir, logger
    )

    if not found:
        return None, None, None, "missing"

    if not implied_moves or not actual_moves:
        return None, None, None, "empty"

    win_rate, avg_excess = compute_implied_vs_actual_stats(implied_moves, actual_moves)

    if win_rate is None:
        return None, None, None, "empty"

    return win_rate, avg_excess, None, "ok"


def observed_us_holiday(raw_date: date) -> date:
    if raw_date.weekday() == 5:
        return raw_date - timedelta(days=1)
    if raw_date.weekday() == 6:
        return raw_date + timedelta(days=1)
    return raw_date


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(
        year if month < 12 else year + 1, month + 1 if month < 12 else 1, 1
    )
    last = next_month - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


_HOLIDAY_CACHE: Dict[int, List[date]] = {}


def us_market_holidays(year: int) -> List[date]:
    if year in _HOLIDAY_CACHE:
        return _HOLIDAY_CACHE[year]

    holidays: List[date] = []
    holidays.append(observed_us_holiday(date(year, 1, 1)))
    holidays.append(nth_weekday(year, 1, 0, 3))
    holidays.append(nth_weekday(year, 2, 0, 3))
    holidays.append(easter_date(year) - timedelta(days=2))
    holidays.append(last_weekday(year, 5, 0))
    holidays.append(observed_us_holiday(date(year, 6, 19)))
    holidays.append(observed_us_holiday(date(year, 7, 4)))
    holidays.append(nth_weekday(year, 9, 0, 1))
    holidays.append(nth_weekday(year, 11, 3, 4))
    holidays.append(observed_us_holiday(date(year, 12, 25)))

    _HOLIDAY_CACHE[year] = holidays
    return holidays


def is_us_market_holiday(check_date: date) -> bool:
    years = {check_date.year, check_date.year - 1, check_date.year + 1}
    return any(check_date in us_market_holidays(year) for year in years)


def next_manual_trading_day(start_date: date) -> date:
    candidate = start_date
    while True:
        if candidate.weekday() < 5 and not is_us_market_holiday(candidate):
            return candidate
        candidate += timedelta(days=1)


def _normalize_si_timestamp(today_ts: Optional[object]) -> pd.Timestamp:
    if today_ts is None:
        return pd.Timestamp.now(TZ_LJUBLJANA)

    if isinstance(today_ts, pd.Timestamp):
        ts = today_ts
    else:
        ts = pd.Timestamp(today_ts)

    if ts.tzinfo is None:
        ts = ts.tz_localize(TZ_LJUBLJANA)
    else:
        ts = ts.tz_convert(TZ_LJUBLJANA)
    return ts


def next_nasdaq_trading_day(today_ts: Optional[object] = None) -> date:
    si_now = _normalize_si_timestamp(today_ts)
    si_tomorrow = si_now + pd.Timedelta(days=1)
    ny_tomorrow = si_tomorrow.tz_convert(TZ_NEW_YORK)
    target_ny_date = ny_tomorrow.date()

    if mcal is not None:  # pragma: no branch
        for calendar_name in CALENDAR_NAMES:
            try:
                calendar = mcal.get_calendar(calendar_name)
            except Exception as exc:  # pragma: no cover
                LOG.debug("Calendar %s unavailable: %s", calendar_name, exc)
                continue

            try:
                schedule = calendar.schedule(
                    start_date=target_ny_date - timedelta(days=1),
                    end_date=target_ny_date + timedelta(days=14),
                )
            except Exception as exc:  # pragma: no cover
                LOG.debug("Calendar %s schedule error: %s", calendar_name, exc)
                continue

            if schedule.empty:
                continue

            for session_label, row in schedule.iterrows():
                session_date = pd.Timestamp(session_label).date()
                if session_date < target_ny_date:
                    continue

                session_length = row["market_close"] - row["market_open"]
                if session_length < pd.Timedelta(hours=6, minutes=30):
                    # skip half-days
                    continue

                return session_date

    LOG.debug("Falling back to manual trading-day logic for %s", target_ny_date)
    # fallback to manual scheduler
    return next_manual_trading_day(target_ny_date)


def determine_target_date(override: Optional[str]) -> date:
    if override:
        try:
            return datetime.strptime(override, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SystemExit(
                f"Invalid --date value {override!r}. Expected YYYY-MM-DD."
            ) from exc

    return next_nasdaq_trading_day()


def load_tickers_from_env(target_date: date) -> Optional[List[str]]:
    csv_path = os.getenv("EARNINGS_CSV")
    if not csv_path:
        return None

    path = Path(csv_path).expanduser()
    if not path.exists():
        raise SystemExit(f"EARNINGS_CSV points to {path}, but the file does not exist.")

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise SystemExit(f"Failed to read CSV from {path}: {exc}") from exc

    ticker_column = None
    for col in df.columns:
        norm = col.strip().lower()
        if norm in {"ticker", "tickers", "symbol", "symbols"}:
            ticker_column = col
            break

    if ticker_column is None:
        raise SystemExit("EARNINGS_CSV must contain a ticker/symbol column.")

    tickers = df[ticker_column].dropna().astype(str)
    date_columns = [col for col in df.columns if "date" in col.lower()]
    if date_columns:
        target_str = target_date.strftime("%Y-%m-%d")
        filtered = pd.Series(dtype=str)
        for col in date_columns:
            try:
                parsed = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")
                mask = parsed == target_str
                filtered = pd.concat([filtered, tickers[mask]])
            except Exception:
                continue
        if not filtered.empty:
            tickers = filtered

    return [t.strip().upper() for t in tickers if t.strip()]


def fetch_nasdaq_tickers(target_date: date, client: HttpClient) -> Optional[List[str]]:
    params = {"date": target_date.strftime("%Y-%m-%d")}
    url = f"{NASDAQ_CALENDAR_URL}?{urlencode(params)}"
    cache_key = f"nasdaq_{target_date.strftime('%Y%m%d')}"
    try:
        text = client.get(url, cache_key=cache_key)
    except Exception:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    rows = payload.get("data", {}).get("rows")
    if not rows:
        return None

    tickers: List[str] = []
    for row in rows:
        symbol = row.get("symbol") or row.get("companysymbol")
        if symbol:
            tickers.append(symbol.strip().upper())
    return tickers or None


def parse_cli_tickers(arg: Optional[str]) -> List[str]:
    if not arg:
        return []
    return [token.strip().upper() for token in arg.split(",") if token.strip()]


def get_earnings_tickers(
    target_date: date,
    args: argparse.Namespace,
    client: HttpClient,
) -> List[str]:
    if args.tickers:
        cli_tickers = parse_cli_tickers(args.tickers)
        if not cli_tickers:
            raise SystemExit("No tickers provided via --tickers.")
        LOG.info("using tickers from cli (%d)", len(cli_tickers))
        return sorted(dict.fromkeys(cli_tickers))

    env_tickers = load_tickers_from_env(target_date)
    if env_tickers:
        LOG.info("using tickers from env csv (%d)", len(env_tickers))
        return sorted(set(env_tickers))

    nasdaq_tickers = fetch_nasdaq_tickers(target_date, client)
    if nasdaq_tickers:
        LOG.info("using tickers from calendar (%d)", len(nasdaq_tickers))
        return sorted(set(nasdaq_tickers))

    raise SystemExit(
        "Unable to determine earnings tickers. Provide --tickers or set EARNINGS_CSV."
    )


def classify(avg_volume_ok: bool, iv_rv_ok: bool, ts_slope_ok: bool) -> str:
    if avg_volume_ok and iv_rv_ok and ts_slope_ok:
        return "Recommended"
    if ts_slope_ok and (
        (avg_volume_ok and not iv_rv_ok) or (iv_rv_ok and not avg_volume_ok)
    ):
        return "Consider"
    return "Avoid"


def compute_metrics(
    ticker: str, stock_obj: Optional[yf.Ticker] = None
) -> Dict[str, Optional[float]]:  # pragma: no cover
    metrics = compute_base_metrics(ticker, stock_obj=stock_obj)
    classification = classify(
        metrics["avg_volume_ok"], metrics["iv_rv_ok"], metrics["ts_slope_ok"]
    )
    metrics = dict(metrics)
    metrics["classification"] = classification
    return metrics


def format_results_for_csv(results: Iterable[TickerResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        recommendation = (r.classification or "").lower()
        if recommendation not in {"recommended", "consider", "avoid"}:
            recommendation = "skip"
        rows.append(
            {
                "ticker": r.ticker,
                "iv_rv_ratio": r.iv_rv_ratio,
                "ts_slope": r.ts_slope,
                "avg_volume": int(r.avg_volume) if r.avg_volume is not None else None,
                "uw_win_rate": r.uw_win_rate,
                "uw_avg_excess": r.uw_avg_excess,
                "recommendation": recommendation,
            }
        )
    return pd.DataFrame(rows, columns=ALL_COLUMNS)


def prepare_csv_frame(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    if "iv_rv_ratio" in data.columns:
        data["iv_rv_ratio"] = data["iv_rv_ratio"].apply(
            lambda v: round(float(v), 4) if pd.notna(v) else np.nan
        )
    if "ts_slope" in data.columns:
        data["ts_slope"] = data["ts_slope"].apply(
            lambda v: round(float(v), 5) if pd.notna(v) else np.nan
        )
    if "avg_volume" in data.columns:
        data["avg_volume"] = data["avg_volume"].apply(
            lambda v: int(v) if pd.notna(v) else np.nan
        )
    if "uw_win_rate" in data.columns:
        data["uw_win_rate"] = data["uw_win_rate"].apply(
            lambda v: round(float(v), 1) if pd.notna(v) else np.nan
        )
    if "uw_avg_excess" in data.columns:
        data["uw_avg_excess"] = data["uw_avg_excess"].apply(
            lambda v: round(float(v), 2) if pd.notna(v) else np.nan
        )
    return data


def save_csv(df: pd.DataFrame, target: object, include_recommendation: bool) -> None:
    data = prepare_csv_frame(df)

    columns = list(RECOMMENDED_COLUMNS)
    if include_recommendation:
        columns.append("recommendation")
    # allow piping to stdout
    if isinstance(target, str) and target == "-":
        data.to_csv(sys.stdout, columns=columns, index=False)
        sys.stdout.flush()
        return

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, columns=columns, index=False)


def format_display_frame(df: pd.DataFrame) -> pd.DataFrame:
    formatted = prepare_csv_frame(df)

    def _fmt(value):
        if pd.isna(value):
            return "N/A"
        if isinstance(value, (int, np.integer)):
            return str(value)
        if isinstance(value, float):
            return str(int(value)) if float(value).is_integer() else f"{value}"
        return str(value)

    for col in formatted.columns:
        formatted[col] = formatted[col].apply(_fmt)
    return formatted


def render_table_output(df: pd.DataFrame) -> None:
    if df.empty:
        print("No Recommended tickers found.")
        return
    display = format_display_frame(df)
    if Console and Table:
        table = Table()
        for col in display.columns:
            table.add_column(col)
        console = Console()
        for _, row in display.iterrows():
            table.add_row(*[str(x) for x in row.tolist()])
        console.print(table)
    elif tabulate:
        print(
            tabulate(
                display.values.tolist(),
                headers=list(display.columns),
                tablefmt="github",
            )
        )
    else:
        print(display.to_string(index=False))


def render_markdown_output(df: pd.DataFrame) -> None:
    if df.empty:
        print("| No Recommended |")
        return
    display = format_display_frame(df)
    try:
        print(display.to_markdown(index=False))
    except Exception:
        if tabulate:
            print(
                tabulate(
                    display.values.tolist(),
                    headers=list(display.columns),
                    tablefmt="github",
                )
            )
        else:
            print(display.to_string(index=False))


def render_json_output(df: pd.DataFrame) -> None:
    payload = prepare_csv_frame(df).replace({np.nan: None})
    print(json.dumps(payload.to_dict(orient="records"), indent=2))


def render_stdout_output(df: pd.DataFrame, style: str) -> None:
    if style == "table":
        render_table_output(df)
    elif style == "md":
        render_markdown_output(df)
    elif style == "json":
        render_json_output(df)


def recommended_sort_key(result: TickerResult) -> Tuple[float, float, float]:
    iv = result.iv_rv_ratio
    slope = result.ts_slope
    vol = result.avg_volume
    # sort strongest first
    return (
        -iv if iv is not None else float("inf"),
        slope if slope is not None else float("inf"),
        -vol if vol is not None else float("inf"),
    )


def process_ticker(
    ticker: str,
    cache_dir: Optional[Path],
    logger: logging.Logger,
    uw_enabled: bool,
) -> TaskOutcome:
    errors: List[str] = []
    metrics_status = "fail"
    uw_status = "skip"
    metrics: Optional[Dict[str, Optional[float]]] = None
    stock: Optional[yf.Ticker] = None

    try:
        stock = yf.Ticker(ticker)
        if not getattr(stock, "options", []):
            result = TickerResult(
                ticker=ticker,
                iv_rv_ratio=None,
                ts_slope=None,
                avg_volume=None,
                classification=None,
                uw_win_rate=None,
                uw_avg_excess=None,
            )
            return TaskOutcome(
                result=result, metrics_status="skip", uw_status="skip", errors=errors
            )
    except Exception as exc:
        errors.append(f"{ticker}: Failed to load options metadata ({exc})")
        result = TickerResult(
            ticker=ticker,
            iv_rv_ratio=None,
            ts_slope=None,
            avg_volume=None,
            classification=None,
            uw_win_rate=None,
            uw_avg_excess=None,
        )
        return TaskOutcome(
            result=result, metrics_status="fail", uw_status="skip", errors=errors
        )

    try:
        metrics = compute_metrics(ticker, stock_obj=stock)
        metrics_status = "ok"
    except MetricsError as exc:
        errors.append(f"{ticker}: {exc}")

    win_rate = None
    avg_excess = None
    if metrics_status == "ok" and uw_enabled:
        win_rate, avg_excess, uw_error, uw_status = fetch_unusual_whales_stats(
            ticker, cache_dir, logger
        )
        if uw_error:
            errors.append(uw_error)
    elif metrics_status == "ok" and not uw_enabled:
        uw_status = "disabled"

    result = TickerResult(
        ticker=ticker,
        iv_rv_ratio=metrics.get("iv_rv_ratio") if metrics else None,
        ts_slope=metrics.get("ts_slope") if metrics else None,
        avg_volume=metrics.get("avg_volume") if metrics else None,
        classification=metrics.get("classification") if metrics else None,
        uw_win_rate=win_rate,
        uw_avg_excess=avg_excess,
    )

    return TaskOutcome(
        result=result, metrics_status=metrics_status, uw_status=uw_status, errors=errors
    )


def print_summary(results: Sequence[TickerResult], errors: Sequence[str]) -> None:
    counts = Counter((r.classification or "skip").lower() for r in results)
    total = len(results)
    error_count = len(set(errors))
    summary = (
        f"Summary: {total} tickers | "
        f"recommended {counts.get('recommended', 0)} | "
        f"consider {counts.get('consider', 0)} | "
        f"avoid {counts.get('avoid', 0)} | "
        f"skip {counts.get('skip', 0)} | "
        f"errors {error_count}"
    )
    print(summary, file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    logger = setup_logging(args.log_level)

    target_date = determine_target_date(args.date)
    cache_dir = CACHE_ROOT / target_date.strftime("%Y-%m-%d") if args.cache else None
    limiter = RateLimiter(args.rps) if args.rps > 0 else None
    client = HttpClient(limiter=limiter, cache_dir=cache_dir, logger=logger)

    tickers = get_earnings_tickers(target_date, args, client)

    print(f"Target earnings date: {target_date}", file=sys.stderr)
    print(f"Total tickers to evaluate: {len(tickers)}", file=sys.stderr)

    results: List[TickerResult] = []
    errors: List[str] = []

    workers = max(1, args.workers)
    # fan out per ticker
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_ticker = {
            executor.submit(
                process_ticker, ticker, cache_dir, logger, not args.no_uw
            ): ticker
            for ticker in tickers
        }
        for index, future in enumerate(
            concurrent.futures.as_completed(future_to_ticker), start=1
        ):
            ticker = future_to_ticker[future]
            try:
                outcome = future.result()
            except Exception as exc:  # pragma: no cover
                msg = f"{ticker}: unexpected error ({exc})"
                print(msg, file=sys.stderr)
                errors.append(msg)
                continue

            results.append(outcome.result)
            errors.extend(outcome.errors)
            print(
                f"[{index}/{len(tickers)}] {ticker} - calc {outcome.metrics_status}; UW {outcome.uw_status}",
                file=sys.stderr,
            )

    recommended = [
        r for r in results if (r.classification or "").lower() == "recommended"
    ]
    recommended.sort(key=recommended_sort_key)

    recommended_df = pd.DataFrame(
        [
            {
                "ticker": r.ticker,
                "iv_rv_ratio": r.iv_rv_ratio,
                "ts_slope": r.ts_slope,
                "avg_volume": r.avg_volume,
                "uw_win_rate": r.uw_win_rate,
                "uw_avg_excess": r.uw_avg_excess,
            }
            for r in recommended
        ],
        columns=RECOMMENDED_COLUMNS,
    )

    all_df = format_results_for_csv(results)

    if args.out != "-":
        save_csv(all_df, args.out, include_recommendation=True)
        print(f"Saved report to {args.out}", file=sys.stderr)
        if args.style == "csv":
            print(f"Recommended setups for {target_date}")
            render_table_output(recommended_df)
    elif args.style == "csv":
        save_csv(recommended_df, "-", include_recommendation=False)

    if args.style == "table":
        print(f"Recommended setups for {target_date}")
        render_stdout_output(recommended_df, args.style)
    elif args.style == "md":
        print(f"Recommended setups for {target_date}")
        render_stdout_output(recommended_df, args.style)
    elif args.style == "json":
        print(f"Recommended setups for {target_date}", file=sys.stderr)
        render_stdout_output(recommended_df, args.style)

    if args.save_all:
        save_csv(all_df, args.save_all, include_recommendation=True)
        print(f"Saved full results to {args.save_all}", file=sys.stderr)

    if errors:
        unique_errors = sorted(set(errors))
        print("Errors:", file=sys.stderr)
        for err in unique_errors:
            print(f" - {err}", file=sys.stderr)

    print_summary(results, errors)


if __name__ == "__main__":
    main()
