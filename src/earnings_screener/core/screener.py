"""Main screening engine."""

import concurrent.futures
import logging
from datetime import date
from typing import List, Optional

import yfinance as yf

from ..config import ScreenerConfig
from ..data import CalendarFetcher, UnusualWhalesScraper
from ..utils import CacheManager, HttpClient, RateLimiter
from .metrics import MetricsCalculator, MetricsError
from .models import ScreenResult, TickerAnalysis, TradeQuality


class EarningsScreener:
    """Main earnings screening engine."""

    def __init__(self, config: ScreenerConfig, logger: Optional[logging.Logger] = None):
        """
        Initialize screener.

        Args:
            config: Screener configuration
            logger: Optional logger
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # Initialize components
        limiter = RateLimiter(config.rps) if config.rps > 0 else None
        cache = CacheManager() if not config.cache_enabled else None

        self.http_client = HttpClient(limiter=limiter, cache=cache, logger=self.logger)
        self.calendar = CalendarFetcher(self.http_client)
        self.uw_scraper = UnusualWhalesScraper(cache=cache, logger=self.logger) if config.include_uw_stats else None
        self.metrics_calc = MetricsCalculator()

    def screen(
        self,
        target_date: Optional[date] = None,
        tickers: Optional[str] = None,
        csv_path: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> ScreenResult:
        """
        Screen tickers for calendar spread opportunities.

        Args:
            target_date: Optional target date. If None, uses next trading day.
            tickers: Optional comma-separated ticker list
            csv_path: Optional path to CSV with tickers
            progress_callback: Optional callback function(ticker_symbol) for progress updates

        Returns:
            ScreenResult with analysis
        """
        # Determine target date
        if target_date is None:
            target_date = self.calendar.get_next_trading_day()

        # Get tickers
        ticker_list = self.calendar.get_tickers_for_date(
            target_date,
            cli_tickers=tickers,
            csv_path=csv_path
        )

        self.logger.info(f"Screening {len(ticker_list)} tickers for {target_date}")

        # Process tickers concurrently
        premium_setups = []
        quality_setups = []
        standard_setups = []
        skipped = []
        errors = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            future_to_ticker = {
                executor.submit(self._analyze_ticker, ticker): ticker
                for ticker in ticker_list
            }

            for future in concurrent.futures.as_completed(future_to_ticker):
                ticker = future_to_ticker[future]

                try:
                    analysis, error_msg = future.result()

                    if error_msg:
                        errors.append(error_msg)

                    if analysis:
                        if analysis.quality == TradeQuality.PREMIUM:
                            premium_setups.append(analysis)
                        elif analysis.quality == TradeQuality.QUALITY:
                            quality_setups.append(analysis)
                        elif analysis.quality == TradeQuality.STANDARD:
                            standard_setups.append(analysis)
                        else:
                            skipped.append(ticker)
                    else:
                        skipped.append(ticker)

                except Exception as exc:
                    self.logger.error(f"{ticker}: Unexpected error - {exc}")
                    errors.append(f"{ticker}: {exc}")
                    skipped.append(ticker)

                # Call progress callback
                if progress_callback:
                    progress_callback(ticker)

        # Sort results by quality metrics
        premium_setups.sort(key=self._sort_key)
        quality_setups.sort(key=self._sort_key)
        standard_setups.sort(key=self._sort_key)

        return ScreenResult(
            date=target_date.strftime("%Y-%m-%d"),
            total_analyzed=len(ticker_list),
            premium_setups=premium_setups,
            quality_setups=quality_setups,
            standard_setups=standard_setups,
            skipped=skipped,
            errors=errors,
        )

    def _analyze_ticker(self, ticker: str) -> tuple[Optional[TickerAnalysis], Optional[str]]:
        """
        Analyze a single ticker.

        Returns:
            Tuple of (TickerAnalysis or None, error_message or None)
        """
        error_msg = None

        try:
            # Check if options available
            stock = yf.Ticker(ticker)
            if not getattr(stock, "options", []):
                return None, None  # Skip without error

            # Calculate metrics
            metrics = self.metrics_calc.calculate(ticker, stock_obj=stock)

            # Get UnusualWhales stats if enabled
            uw_win_rate = None
            uw_avg_profit = None

            if self.uw_scraper and metrics["quality"] != TradeQuality.SKIP:
                uw_win_rate, uw_avg_profit, uw_status = self.uw_scraper.get_stats(ticker)
                if uw_status not in ("ok", "unavailable"):
                    self.logger.debug(f"{ticker}: UW status {uw_status}")

            # Create analysis result
            analysis = TickerAnalysis(
                ticker=ticker,
                iv_rv_ratio=metrics["iv_rv_ratio"],
                term_slope=metrics["ts_slope"],
                avg_volume=metrics["avg_volume"],
                expected_move=metrics["expected_move"],
                uw_win_rate=uw_win_rate,
                uw_avg_profit=uw_avg_profit,
                quality=metrics["quality"],
            )

            return analysis, None

        except MetricsError as exc:
            # Expected - insufficient options data (normal for illiquid stocks)
            # Only log at debug level, don't alarm users
            self.logger.debug(f"{ticker}: {exc}")
            return None, None

        except Exception as exc:
            # Unexpected errors - these are real problems
            self.logger.warning(f"{ticker}: Unexpected error - {exc}")
            error_msg = f"{ticker}: {exc}"
            return None, error_msg

    @staticmethod
    def _sort_key(analysis: TickerAnalysis) -> tuple:
        """Sort key for ranking setups (best first)."""
        iv_rv = analysis.iv_rv_ratio if analysis.iv_rv_ratio else 0
        slope = analysis.term_slope if analysis.term_slope else 0
        volume = analysis.avg_volume if analysis.avg_volume else 0

        # Sort by: highest IV/RV, lowest slope, highest volume
        return (-iv_rv, slope, -volume)
