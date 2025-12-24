# Changelog

All notable changes to the Earnings Calendar Screener will be documented here.

## [2.0.0] - 2024-12-24

### Major rewrite

#### Added
- **Modern Architecture**: Complete rewrite with modular src/ layout
- **CLI output**: Rich-based tables and progress bars
- **Quality Tiers**: Premium/Quality/Standard classification system
- **Performance**: Concurrent processing with 8 workers by default
- **Smart Caching**: Optional disk caching for API responses
- **Flexible Output**: Table, CSV, JSON, and Markdown formats
- **Progress Tracking**: Real-time progress indicators with animations
- **Error handling**: clearer error messages for missing or invalid data
- **Docs**: install, quick-start and usage documentation
- **Type Safety**: Better type hints throughout codebase

#### Changed
- **User-Facing Language**: Removed technical jargon about thresholds
- **Output Format**: Focus on actionable trade opportunities
- **Classification**: Simplified from 4 tiers to 3 clear quality levels
- **CLI Interface**: More intuitive command-line arguments
- **Documentation**: Rewritten for wider public audience
- **Package Name**: earnings-filter → earnings-screener

#### Improved
- **Speed**: 2-3x faster with optimized concurrent processing
- **Reliability**: Better retry logic and error recovery
- **Output**: progress bars and clearer status messages
- **Modularity**: Code split into logical modules for maintainability
- **Logging**: Rich-powered logging with better formatting

#### Technical Improvements
- Modular architecture (core/, data/, ui/, utils/)
- Proper package structure with src/ layout
- Better separation of concerns
- Improved configuration management
- Enhanced rate limiting
- Thread-safe HTTP client
- Clearer error messages

### Removed
- Internal threshold documentation from user-facing output
- Technical implementation details from CLI help
- Confusing terminology ("recommended", "consider", "avoid")
- Batch processing mode (simplified to single mode)

## [1.0.0] - 2024-10-28

### Initial Release
- Basic earnings screening functionality
- NASDAQ calendar integration
- Options metrics calculation (IV/RV, term structure, volume)
- UnusualWhales scraping support
- CSV output
- Basic CLI interface

---

Format based on [Keep a Changelog](https://keepachangelog.com/)
