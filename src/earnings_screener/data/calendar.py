"""Earnings calendar data fetching."""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlencode

import pandas as pd
import pytz

try:
    import pandas_market_calendars as mcal
except ImportError:
    mcal = None

from ..config import CALENDAR_NAMES, NASDAQ_API_URL, TIMEZONE_LOCAL, TIMEZONE_NY
from ..utils import HttpClient


class CalendarFetcher:
    """Fetch earnings calendar data from multiple sources."""

    def __init__(self, http_client: HttpClient):
        """Initialize calendar fetcher."""
        self.http_client = http_client
        self.tz_local = pytz.timezone(TIMEZONE_LOCAL)
        self.tz_ny = pytz.timezone(TIMEZONE_NY)

    def get_tickers_for_date(
        self,
        target_date: date,
        cli_tickers: Optional[str] = None,
        csv_path: Optional[str] = None,
    ) -> List[str]:
        """
        Get tickers for target earnings date.

        Priority:
        1. CLI tickers (if provided)
        2. CSV file from environment or parameter
        3. NASDAQ calendar API

        Args:
            target_date: Date to get earnings for
            cli_tickers: Comma-separated ticker list from CLI
            csv_path: Path to CSV file with tickers

        Returns:
            List of ticker symbols

        Raises:
            ValueError: If no tickers can be determined
        """
        # Priority 1: CLI tickers
        if cli_tickers:
            tickers = [t.strip().upper() for t in cli_tickers.split(",") if t.strip()]
            if tickers:
                return sorted(set(tickers))

        # Priority 2: CSV file
        csv_source = csv_path or os.getenv("EARNINGS_CSV")
        if csv_source:
            tickers = self._load_from_csv(csv_source, target_date)
            if tickers:
                return sorted(set(tickers))

        # Priority 3: NASDAQ API
        tickers = self._fetch_from_nasdaq(target_date)
        if tickers:
            return sorted(set(tickers))

        raise ValueError(
            "Unable to determine earnings tickers. "
            "Please provide --tickers or set EARNINGS_CSV environment variable."
        )

    def get_next_trading_day(self, today_ts: Optional[object] = None) -> date:
        """
        Calculate next trading day aware of market holidays.

        Args:
            today_ts: Optional timestamp for 'today'

        Returns:
            Next trading day
        """
        # Normalize timestamp to local timezone
        if today_ts is None:
            si_now = pd.Timestamp.now(self.tz_local)
        elif isinstance(today_ts, pd.Timestamp):
            ts = today_ts
            si_now = ts.tz_localize(self.tz_local) if ts.tzinfo is None else ts.tz_convert(self.tz_local)
        else:
            ts = pd.Timestamp(today_ts)
            si_now = ts.tz_localize(self.tz_local) if ts.tzinfo is None else ts.tz_convert(self.tz_local)

        # Get tomorrow in NY timezone
        si_tomorrow = si_now + pd.Timedelta(days=1)
        ny_tomorrow = si_tomorrow.tz_convert(self.tz_ny)
        target_ny_date = ny_tomorrow.date()

        # Try market calendars if available
        if mcal is not None:
            for calendar_name in CALENDAR_NAMES:
                try:
                    calendar = mcal.get_calendar(calendar_name)
                    schedule = calendar.schedule(
                        start_date=target_ny_date - timedelta(days=1),
                        end_date=target_ny_date + timedelta(days=14),
                    )

                    if schedule.empty:
                        continue

                    for session_label, row in schedule.iterrows():
                        session_date = pd.Timestamp(session_label).date()
                        if session_date < target_ny_date:
                            continue

                        # Skip half-days (< 6.5 hours)
                        session_length = row["market_close"] - row["market_open"]
                        if session_length < pd.Timedelta(hours=6, minutes=30):
                            continue

                        return session_date

                except Exception:
                    continue

        # Fallback to manual calculation
        return self._next_manual_trading_day(target_ny_date)

    def _load_from_csv(self, csv_path: str, target_date: date) -> Optional[List[str]]:
        """Load tickers from CSV file."""
        try:
            path = Path(csv_path).expanduser()
            if not path.exists():
                return None

            df = pd.read_csv(path)

            # Find ticker column
            ticker_col = None
            for col in df.columns:
                if col.strip().lower() in {"ticker", "tickers", "symbol", "symbols"}:
                    ticker_col = col
                    break

            if ticker_col is None:
                return None

            tickers = df[ticker_col].dropna().astype(str)

            # Filter by date if date column exists
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

        except Exception:
            return None

    def _fetch_from_nasdaq(self, target_date: date) -> Optional[List[str]]:
        """Fetch tickers from NASDAQ calendar API."""
        try:
            params = {"date": target_date.strftime("%Y-%m-%d")}
            url = f"{NASDAQ_API_URL}?{urlencode(params)}"
            cache_key = f"nasdaq_{target_date.strftime('%Y%m%d')}"

            text = self.http_client.get(url, cache_key=cache_key)
            payload = json.loads(text)

            rows = payload.get("data", {}).get("rows")
            if not rows:
                return None

            tickers = []
            for row in rows:
                symbol = row.get("symbol") or row.get("companysymbol")
                if symbol:
                    tickers.append(symbol.strip().upper())

            return tickers or None

        except Exception:
            return None

    def _next_manual_trading_day(self, start_date: date) -> date:
        """Manually calculate next trading day."""
        candidate = start_date

        while True:
            # Skip weekends
            if candidate.weekday() < 5 and not self._is_us_market_holiday(candidate):
                return candidate
            candidate += timedelta(days=1)

    def _is_us_market_holiday(self, check_date: date) -> bool:
        """Check if date is a US market holiday."""
        holidays = self._get_us_market_holidays(check_date.year)

        # Check current year and adjacent years
        for year_offset in [0, -1, 1]:
            year = check_date.year + year_offset
            if check_date in self._get_us_market_holidays(year):
                return True

        return False

    def _get_us_market_holidays(self, year: int) -> List[date]:
        """Get US market holidays for a year."""
        holidays = []

        # New Year's Day
        holidays.append(self._observed_holiday(date(year, 1, 1)))

        # MLK Day (3rd Monday in January)
        holidays.append(self._nth_weekday(year, 1, 0, 3))

        # Presidents Day (3rd Monday in February)
        holidays.append(self._nth_weekday(year, 2, 0, 3))

        # Good Friday
        easter = self._easter_date(year)
        holidays.append(easter - timedelta(days=2))

        # Memorial Day (last Monday in May)
        holidays.append(self._last_weekday(year, 5, 0))

        # Juneteenth
        holidays.append(self._observed_holiday(date(year, 6, 19)))

        # Independence Day
        holidays.append(self._observed_holiday(date(year, 7, 4)))

        # Labor Day (1st Monday in September)
        holidays.append(self._nth_weekday(year, 9, 0, 1))

        # Thanksgiving (4th Thursday in November)
        holidays.append(self._nth_weekday(year, 11, 3, 4))

        # Christmas
        holidays.append(self._observed_holiday(date(year, 12, 25)))

        return holidays

    @staticmethod
    def _observed_holiday(holiday: date) -> date:
        """Get observed date for weekend holidays."""
        if holiday.weekday() == 5:  # Saturday
            return holiday - timedelta(days=1)
        elif holiday.weekday() == 6:  # Sunday
            return holiday + timedelta(days=1)
        return holiday

    @staticmethod
    def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
        """Get nth occurrence of weekday in month."""
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))

    @staticmethod
    def _last_weekday(year: int, month: int, weekday: int) -> date:
        """Get last occurrence of weekday in month."""
        next_month = date(year if month < 12 else year + 1, month + 1 if month < 12 else 1, 1)
        last = next_month - timedelta(days=1)
        offset = (last.weekday() - weekday) % 7
        return last - timedelta(days=offset)

    @staticmethod
    def _easter_date(year: int) -> date:
        """Calculate Easter date using Computus algorithm."""
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
