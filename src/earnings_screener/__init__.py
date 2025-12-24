"""
Earnings Calendar Screener

Screener for identifying calendar spread
opportunities around earnings announcements.
"""

__version__ = "1.0.0"
__author__ = "Earnings Screener Team"

from .core.screener import EarningsScreener

__all__ = ["EarningsScreener"]
