"""Command-line interface."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from rich.console import Console
from rich.logging import RichHandler

from . import __version__
from .config import CACHE_ROOT, ScreenerConfig
from .core import EarningsScreener
from .ui import DisplayManager, ProgressTracker


def setup_logging(level: str) -> None:
    """
    Configure Rich-based logging.

    Args:
        level: Log level (debug, info, warning, error)
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_time=False, show_path=False)]
    )


def parse_date(date_str: str) -> datetime:
    """
    Parse date string.

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        Parsed datetime

    Raises:
        argparse.ArgumentTypeError: If date format is invalid
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: {date_str}. Expected YYYY-MM-DD"
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Earnings calendar screener for option calendar spreads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Screen next earnings date
  earnings-screener

  # Screen specific date
  earnings-screener --date 2024-12-31

  # Screen specific tickers
  earnings-screener --tickers AAPL,MSFT,GOOGL

  # Save to file
  earnings-screener --output results.csv

  # JSON output
  earnings-screener --style json
        """
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"Earnings Screener v{__version__}"
    )

    # Input options
    input_group = parser.add_argument_group("Input Options")
    input_group.add_argument(
        "--date",
        type=parse_date,
        help="Target earnings date (YYYY-MM-DD). Defaults to next trading day."
    )
    input_group.add_argument(
        "--tickers",
        help="Comma-separated list of ticker symbols to screen"
    )
    input_group.add_argument(
        "--csv",
        help="Path to CSV file with tickers (alternative to EARNINGS_CSV env var)"
    )

    # Output options
    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--output", "-o",
        help="Save results to CSV file"
    )
    output_group.add_argument(
        "--style",
        choices=["table", "csv", "json", "markdown"],
        default="table",
        help="Output display style (default: table)"
    )
    output_group.add_argument(
        "--no-summary",
        action="store_true",
        help="Hide summary statistics"
    )

    # Performance options
    perf_group = parser.add_argument_group("Performance Options")
    perf_group.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of concurrent workers (default: 8)"
    )
    perf_group.add_argument(
        "--rps",
        type=float,
        default=1.0,
        help="Requests per second rate limit (default: 1.0)"
    )
    perf_group.add_argument(
        "--cache",
        action="store_true",
        help="Enable disk caching for API responses"
    )

    # Data options
    data_group = parser.add_argument_group("Data Options")
    data_group.add_argument(
        "--no-uw",
        action="store_true",
        help="Skip UnusualWhales historical data (faster but less info)"
    )

    # Debug options
    debug_group = parser.add_argument_group("Debug Options")
    debug_group.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="warning",
        help="Logging verbosity (default: warning)"
    )
    debug_group.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar"
    )

    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Main entry point.

    Args:
        argv: Command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Parse arguments
    args = parse_args(argv)

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger("earnings_screener")

    # Create configuration
    config = ScreenerConfig(
        workers=args.workers,
        rps=args.rps,
        cache_enabled=args.cache,
        include_uw_stats=not args.no_uw,
        log_level=args.log_level,
    )

    # Setup cache directory if enabled
    if config.cache_enabled:
        target_date = args.date.date() if args.date else None
        if target_date:
            cache_dir = CACHE_ROOT / target_date.strftime("%Y-%m-%d")
            cache_dir.mkdir(parents=True, exist_ok=True)

    # Initialize components
    screener = EarningsScreener(config, logger=logger)
    display = DisplayManager()
    console = Console()

    try:
        # Show header
        target_date = args.date.date() if args.date else screener.calendar.get_next_trading_day()

        # Get ticker count for header
        try:
            ticker_list = screener.calendar.get_tickers_for_date(
                target_date,
                cli_tickers=args.tickers,
                csv_path=args.csv
            )
            total_tickers = len(ticker_list)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            return 1

        if args.style == "table" and not args.no_progress:
            display.show_header(target_date.strftime("%Y-%m-%d"), total_tickers)

        # Run screening with progress tracking
        if args.style == "table" and not args.no_progress:
            with ProgressTracker() as progress:
                progress.start_screening(total_tickers)

                def update_progress(ticker: str):
                    progress.update(ticker)

                result = screener.screen(
                    target_date=target_date,
                    tickers=args.tickers,
                    csv_path=args.csv,
                    progress_callback=update_progress
                )

                progress.finish()
        else:
            result = screener.screen(
                target_date=target_date,
                tickers=args.tickers,
                csv_path=args.csv
            )

        # Display results
        display.show_results(result, style=args.style)

        # Show summary
        if args.style == "table" and not args.no_summary:
            display.show_summary(result)

        # Save to file if requested
        if args.output:
            display.save_csv(result, args.output)

        # Return success
        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Screening cancelled by user[/yellow]")
        return 1

    except Exception as exc:
        logger.error(f"Unexpected error: {exc}", exc_info=True)
        console.print(f"[red]Error:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
