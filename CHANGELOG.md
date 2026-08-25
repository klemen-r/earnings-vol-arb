# Changelog

## [1.0.0] - 2025-12-24

First public release.

### Screening

- Term structure of implied volatility built from filtered expirations (up to 45 DTE)
- IV/RV ratio using Yang-Zhang realized volatility
- Liquidity filter on average daily volume
- Quality tiers (Premium / Quality / Standard / Skip) derived from the three criteria above

### Data

- Earnings calendar from Nasdaq, with a market calendar that accounts for holidays and half-days
- Optional historical earnings-move data from UnusualWhales
- Optional on-disk caching of API responses, plus request rate limiting

### Interface

- Command-line interface with Rich tables and progress output
- Table, CSV, JSON and Markdown output formats
- Concurrent screening of multiple tickers
