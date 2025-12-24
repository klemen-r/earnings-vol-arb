# Earnings Calendar Screener

> **Find high-quality calendar spread opportunities around earnings**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A command-line screener for finding calendar spread setups around earnings announcements.

## What Is This?

This screener helps you find calendar spread opportunities around earnings. It checks volatility patterns, liquidity, and historical data to find the best setups.

**Calendar spreads**: Sell front-month options (high IV before earnings) and buy back-month options. Profit from the IV crush after earnings while staying delta-neutral.

## Features

- Clean terminal interface with progress bars
- Concurrent processing (analyze 100+ tickers fast)
- IV/RV ratios, term structure analysis, volume checks
- Optional historical earnings data (UnusualWhales)
- Smart calendar (knows holidays and half-days)
- Built-in caching for speed
- Multiple output formats (table, CSV, JSON, markdown)

## Quick Start

### Installation

```bash
# Install the package
pip install .

# For UnusualWhales support (optional)
pip install .[all]
python -m playwright install chromium
```

### Basic Usage

```bash
# Screen next earnings date
earnings-screener

# Screen specific date
earnings-screener --date 2024-12-31

# Screen specific tickers
earnings-screener --tickers AAPL,MSFT,GOOGL

# Save results to file
earnings-screener --output results.csv

# JSON output for programmatic use
earnings-screener --style json
```

## Usage Examples

### Screen Tomorrow's Earnings

```bash
earnings-screener
```

Output shows premium, quality, and standard setups ranked by opportunity quality.

### High-Performance Screening

```bash
earnings-screener --workers 16 --rps 2.0 --cache
```

- `--workers 16` - Use 16 concurrent workers
- `--rps 2.0` - 2 requests per second
- `--cache` - Enable disk caching

### Save and Export

```bash
# Save to CSV
earnings-screener --output opportunities.csv

# Get JSON for automation
earnings-screener --style json > data.json

# Markdown for reports
earnings-screener --style markdown > report.md
```

### Custom Ticker Lists

```bash
# From command line
earnings-screener --tickers AAPL,MSFT,GOOGL,TSLA

# From CSV file
earnings-screener --csv my_watchlist.csv

# From environment variable
export EARNINGS_CSV=/path/to/tickers.csv
earnings-screener
```

## Understanding the Output

Three quality tiers:

**Premium (*)** - All metrics look great. Best opportunities.

**Quality (+)** - Most metrics strong. Still good setups.

**Standard (-)** - Meets criteria. Worth considering.

### Output Columns

- **Ticker** - Stock symbol
- **Quality** - Setup classification
- **IV/RV** - Implied volatility vs realized volatility ratio (higher is better)
- **Term Slope** - IV term structure slope (negative indicates elevated short-term IV)
- **Avg Volume** - 30-day average volume
- **Expected Move** - Priced-in move based on ATM straddle
- **Win Rate** - Historical % of times selling straddle was profitable
- **Avg Profit** - Average profit per trade from historical data

##  Configuration

### Command-Line Options

```bash
earnings-screener --help
```

Key options:
- `--date YYYY-MM-DD` - Target earnings date
- `--tickers LIST` - Comma-separated tickers
- `--csv PATH` - Path to ticker CSV
- `--output PATH` - Save results to file
- `--style {table,csv,json,markdown}` - Output format
- `--workers N` - Concurrent workers (default: 8)
- `--rps N` - Requests per second (default: 1.0)
- `--cache` - Enable caching
- `--no-uw` - Skip UnusualWhales data (faster)
- `--log-level {debug,info,warning,error}` - Logging verbosity

### Environment Variables

- `EARNINGS_CSV` - Default path to ticker CSV file

### CSV File Format

The CSV should have a `ticker` or `symbol` column:

```csv
ticker,date
AAPL,2024-12-31
MSFT,2024-12-31
GOOGL,2025-01-15
```

If a `date` column exists, only tickers matching the target date are screened.

## Architecture

```
earnings-screener/
├── src/earnings_screener/
│   ├── core/              # Screening engine & metrics
│   ├── data/              # Data fetching (calendar, UnusualWhales)
│   ├── ui/                # Display & progress tracking
│   ├── utils/             # HTTP, caching, rate limiting
│   ├── config.py          # Configuration
│   └── cli.py             # Command-line interface
├── tests/                 # Test suite
└── docs/                  # Documentation
```

## Development

### Setup Development Environment

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/ tests/
isort src/ tests/

# Type checking
mypy src/
```

### Running Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src/earnings_screener --cov-report=html

# Specific test file
pytest tests/test_metrics.py
```

## Trading Strategy

Calendar spreads work like this:

1. Before earnings, IV usually spikes
2. Sell short-dated options (high IV)
3. Buy longer-dated options (lower IV)
4. Profit when IV drops after earnings

The screener finds tickers where:
- IV is pumped up vs historical volatility
- Front-month options are more expensive than back-month
- There's enough volume to actually trade
- Historical data shows it works

## Disclaimer

This is a research tool. Options are risky - you can lose money. Past performance doesn't mean future results. Do your own research before trading. Not financial advice.

## License

MIT License - see [LICENSE](LICENSE) file for details

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/earnings-screener/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/earnings-screener/discussions)

---

Built for options traders
