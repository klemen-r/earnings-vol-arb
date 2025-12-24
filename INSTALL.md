# Installation Guide

## Quick Install

```bash
# Navigate to the project directory
cd earnings-screener

# Install the package
pip install .
```

## Installation with Optional Features

### UnusualWhales Support

For historical earnings data analysis:

```bash
pip install .[all]
python -m playwright install chromium
```

### Development Installation

For contributing to the project:

```bash
pip install -e ".[dev]"
```

## System Requirements

- **Python**: 3.10 or higher
- **Operating System**: Windows, macOS, or Linux
- **RAM**: 2GB minimum, 4GB recommended
- **Internet**: Required for data fetching

## Verifying Installation

```bash
# Check version
earnings-screener --version

# Run a quick test
earnings-screener --tickers AAPL --no-uw
```

## Troubleshooting

### Import Errors

If you see import errors, make sure you're installing from the project root:

```bash
cd /path/to/earnings-screener
pip install .
```

### Playwright Issues

If UnusualWhales scraping fails:

```bash
# Reinstall playwright browsers
python -m playwright install chromium

# Or skip UW entirely
earnings-screener --no-uw
```

### Permission Errors

On Linux/macOS, you might need:

```bash
pip install --user .
```

Or use a virtual environment (recommended):

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install .
```

## Updating

To update to the latest version:

```bash
cd earnings-screener
git pull  # If using git
pip install --upgrade .
```

## Uninstalling

```bash
pip uninstall earnings-screener
```

## Next Steps

After installation, see [README.md](README.md) for usage examples.
