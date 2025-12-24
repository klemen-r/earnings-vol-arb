@echo off
REM Quick launch script for Windows users

echo ================================================
echo   EARNINGS CALENDAR SCREENER
echo ================================================
echo.

python -m earnings_screener.cli %*

echo.
pause
