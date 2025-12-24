"""Display and output formatting."""

import sys
from typing import List, Optional

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import Colors
from ..core.models import ScreenResult, TickerAnalysis, TradeQuality


class DisplayManager:
    """Render screening results to the terminal."""

    def __init__(self):
        """Initialize display manager."""
        self.console = Console()

    def show_header(self, date: str, total_tickers: int) -> None:
        """
        Display application header.

        Args:
            date: Target earnings date
            total_tickers: Total number of tickers to analyze
        """
        title = Text("EARNINGS CALENDAR SCREENER", style="bold white on blue")
        subtitle = Text(
            f"Screening {total_tickers} tickers for {date}",
            style="dim"
        )

        header_panel = Panel(
            Text.assemble(title, "\n", subtitle),
            border_style="blue",
            padding=(1, 2)
        )

        self.console.print()
        self.console.print(header_panel)
        self.console.print()

    def show_results(self, result: ScreenResult, style: str = "table") -> None:
        """
        Display screening results.

        Args:
            result: Screen results
            style: Output style (table, csv, json, markdown)
        """
        if style == "table":
            self._show_table_results(result)
        elif style == "csv":
            self._show_csv_results(result)
        elif style == "json":
            self._show_json_results(result)
        elif style == "markdown":
            self._show_markdown_results(result)

    def show_summary(self, result: ScreenResult) -> None:
        """
        Display summary statistics.

        Args:
            result: Screen results
        """
        # Create summary stats
        stats_text = Text()
        stats_text.append("[STATS] ", style="bold blue")
        stats_text.append(f"{result.total_opportunities}", style="bold green")
        stats_text.append(" trade opportunities found\n", style="")

        if result.premium_setups:
            stats_text.append("  * ", style="bold green")
            stats_text.append(f"{len(result.premium_setups)} Premium", style="bold green")
            stats_text.append(" setups\n", style="")

        if result.quality_setups:
            stats_text.append("  + ", style="bold cyan")
            stats_text.append(f"{len(result.quality_setups)} Quality", style="bold cyan")
            stats_text.append(" setups\n", style="")

        if result.standard_setups:
            stats_text.append("  - ", style="bold yellow")
            stats_text.append(f"{len(result.standard_setups)} Standard", style="bold yellow")
            stats_text.append(" setups\n", style="")

        if result.errors:
            stats_text.append(f"  ! {len(result.errors)} errors", style="dim yellow")

        summary_panel = Panel(
            stats_text,
            title="[bold]Summary[/bold]",
            border_style="green",
            padding=(1, 2)
        )

        self.console.print()
        self.console.print(summary_panel)
        self.console.print()

    def _show_table_results(self, result: ScreenResult) -> None:
        """Display results as formatted table."""
        all_setups = result.premium_setups + result.quality_setups + result.standard_setups

        if not all_setups:
            self.console.print(
                Panel(
                    "[yellow]No trade opportunities found for this date.[/yellow]",
                    border_style="yellow"
                )
            )
            return

        # Create table
        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            title=f"[bold]Calendar Spread Opportunities - {result.date}[/bold]",
            title_style="bold white"
        )

        table.add_column("Ticker", style="bold white", no_wrap=True)
        table.add_column("Quality", justify="center")
        table.add_column("IV/RV", justify="right")
        table.add_column("Term Slope", justify="right")
        table.add_column("Avg Volume", justify="right")
        table.add_column("Expected Move", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Avg Profit", justify="right")

        # Add rows
        for setup in all_setups:
            # Quality indicator
            if setup.quality == TradeQuality.PREMIUM:
                quality_display = "[bold green]* Premium[/bold green]"
            elif setup.quality == TradeQuality.QUALITY:
                quality_display = "[bold cyan]+ Quality[/bold cyan]"
            else:
                quality_display = "[yellow]- Standard[/yellow]"

            # Format values
            iv_rv = f"{setup.iv_rv_ratio:.2f}" if setup.iv_rv_ratio else "[dim]N/A[/dim]"
            slope = f"{setup.term_slope:.5f}" if setup.term_slope else "[dim]N/A[/dim]"
            volume = f"{int(setup.avg_volume):,}" if setup.avg_volume else "[dim]N/A[/dim]"
            exp_move = f"{setup.expected_move:.1f}%" if setup.expected_move else "[dim]N/A[/dim]"
            win_rate = f"{setup.uw_win_rate:.0f}%" if setup.uw_win_rate else "[dim]N/A[/dim]"
            avg_profit = f"{setup.uw_avg_profit:.1f}%" if setup.uw_avg_profit else "[dim]N/A[/dim]"

            table.add_row(
                setup.ticker,
                quality_display,
                iv_rv,
                slope,
                volume,
                exp_move,
                win_rate,
                avg_profit
            )

        self.console.print(table)
        self.console.print()

    def _show_csv_results(self, result: ScreenResult) -> None:
        """Display results as CSV."""
        all_setups = result.premium_setups + result.quality_setups + result.standard_setups

        if not all_setups:
            return

        df = self._create_dataframe(all_setups)
        df.to_csv(sys.stdout, index=False)

    def _show_json_results(self, result: ScreenResult) -> None:
        """Display results as JSON."""
        import json

        all_setups = result.premium_setups + result.quality_setups + result.standard_setups

        data = []
        for setup in all_setups:
            data.append({
                "ticker": setup.ticker,
                "quality": setup.quality.value,
                "iv_rv_ratio": setup.iv_rv_ratio,
                "term_slope": setup.term_slope,
                "avg_volume": int(setup.avg_volume) if setup.avg_volume else None,
                "expected_move": setup.expected_move,
                "uw_win_rate": setup.uw_win_rate,
                "uw_avg_profit": setup.uw_avg_profit,
            })

        print(json.dumps(data, indent=2))

    def _show_markdown_results(self, result: ScreenResult) -> None:
        """Display results as Markdown."""
        all_setups = result.premium_setups + result.quality_setups + result.standard_setups

        if not all_setups:
            print("No opportunities found.")
            return

        df = self._create_dataframe(all_setups)

        try:
            print(df.to_markdown(index=False))
        except AttributeError:
            # Fallback if to_markdown not available
            from tabulate import tabulate
            print(tabulate(df, headers="keys", tablefmt="github", showindex=False))

    def _create_dataframe(self, setups: List[TickerAnalysis]) -> pd.DataFrame:
        """Create pandas DataFrame from setups."""
        data = []

        for setup in setups:
            data.append({
                "ticker": setup.ticker,
                "quality": setup.quality.value,
                "iv_rv_ratio": round(setup.iv_rv_ratio, 2) if setup.iv_rv_ratio else None,
                "term_slope": round(setup.term_slope, 5) if setup.term_slope else None,
                "avg_volume": int(setup.avg_volume) if setup.avg_volume else None,
                "expected_move": round(setup.expected_move, 1) if setup.expected_move else None,
                "uw_win_rate": round(setup.uw_win_rate, 0) if setup.uw_win_rate else None,
                "uw_avg_profit": round(setup.uw_avg_profit, 1) if setup.uw_avg_profit else None,
            })

        return pd.DataFrame(data)

    def save_csv(self, result: ScreenResult, path: str) -> None:
        """
        Save results to CSV file.

        Args:
            result: Screen results
            path: Output file path
        """
        all_setups = result.premium_setups + result.quality_setups + result.standard_setups
        df = self._create_dataframe(all_setups)
        df.to_csv(path, index=False)

        self.console.print(f"[green]>[/green] Results saved to [cyan]{path}[/cyan]")
