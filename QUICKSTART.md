# Quick Start Guide

## Installation (30 seconds)

```bash
pip install .
```

That's it! The screener is ready to use.

## Your First Screen (10 seconds)

```bash
python -m earnings_screener.cli --tickers AAPL --no-uw
```

This will analyze AAPL without historical data (faster for testing).

## Examples

### 1. Screen Tomorrow's Earnings

```bash
python -m earnings_screener.cli
```

Table output with all opportunities ranked by quality.

### 2. Quick Test with Specific Tickers

```bash
python -m earnings_screener.cli --tickers AAPL,MSFT,GOOGL --no-uw
```

Fast mode without UnusualWhales data.

### 3. Save Results

```bash
python -m earnings_screener.cli --output my_opportunities.csv
```

### 4. Export as JSON

```bash
python -m earnings_screener.cli --style json > data.json
```

### 5. Maximum Performance

```bash
python -m earnings_screener.cli --workers 16 --rps 2.0 --cache
```

## Understanding the Output

### Quality Tiers

- **Premium** - all metrics pass the configured thresholds
- **Quality** - most metrics pass the thresholds
- **• Standard** - Good opportunities (meets minimum criteria)

### Key Metrics

- **IV/RV** - Higher is better (shows elevated volatility)
- **Term Slope** - Negative shows front-month IV elevation
- **Avg Volume** - Higher ensures better liquidity
- **Expected Move** - What the market is pricing in
- **Win Rate** - Historical success rate (requires UW data)
- **Avg Profit** - Average historical profit (requires UW data)

## Common Commands

```bash
# Get help
python -m earnings_screener.cli --help

# Screen specific date
python -m earnings_screener.cli --date 2024-12-31

# Use custom ticker list
python -m earnings_screener.cli --csv my_tickers.csv

# Different output styles
python -m earnings_screener.cli --style table    # Table output (default)
python -m earnings_screener.cli --style csv      # CSV to stdout
python -m earnings_screener.cli --style json     # JSON format
python -m earnings_screener.cli --style markdown # Markdown table
```

## Tips

1. **Start without UW data** (`--no-uw`) for faster testing
2. **Enable caching** (`--cache`) to speed up repeated runs
3. **Increase workers** (`--workers 16`) for better performance
4. **Save results** (`--output file.csv`) for later analysis
5. **Use JSON output** (`--style json`) for automation

## Next Steps

- Read [README.md](README.md) for full documentation
- See [INSTALL.md](INSTALL.md) for advanced installation
- Check examples in the documentation

## Need Help?

```bash
python -m earnings_screener.cli --help
```


