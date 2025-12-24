"""Progress tracking and display."""

from typing import Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)


class ProgressTracker:
    """Track and display screening progress."""

    def __init__(self):
        """Initialize progress tracker."""
        self.console = Console()
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(complete_style="green", finished_style="bold green"),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            console=self.console,
        )
        self.task_id: Optional[TaskID] = None

    def __enter__(self):
        """Enter context manager."""
        self.progress.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        return self.progress.__exit__(exc_type, exc_val, exc_tb)

    def start_screening(self, total: int) -> TaskID:
        """
        Start screening progress.

        Args:
            total: Total number of tickers to screen

        Returns:
            Task ID for updates
        """
        self.task_id = self.progress.add_task(
            "Analyzing opportunities...",
            total=total
        )
        return self.task_id

    def update(self, ticker: str, advance: int = 1) -> None:
        """
        Update progress.

        Args:
            ticker: Current ticker being processed
            advance: Amount to advance progress
        """
        if self.task_id is not None:
            self.progress.update(
                self.task_id,
                advance=advance,
                description=f"Analyzing [cyan]{ticker}[/cyan]..."
            )

    def finish(self, message: str = "Analysis complete!") -> None:
        """
        Finish progress tracking.

        Args:
            message: Completion message
        """
        if self.task_id is not None:
            self.progress.update(
                self.task_id,
                description=f"[bold green]:heavy_check_mark:[/bold green] {message}"
            )
