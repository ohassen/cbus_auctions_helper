# Auction Monitor CLI

A Python CLI tool that monitors auction websites daily for specific items, uses AI semantic matching to filter results, and emails detailed reports.

## Features

- **Web Scraping**: Monitors two auction sites with Playwright:
  - Capital City Online Auction (capitalcityonlineauction.com)
  - BidFTA (Columbus-area locations only)

- **AI Semantic Matching**: Uses Claude to evaluate item relevance with:
  - Vision analysis of product images
  - Intelligent filtering of false positives
  - Configurable relevance threshold

- **Price Intelligence**:
  - Extracts MSRP from listings
  - Looks up retail prices via Claude when unavailable
  - Calculates discount percentages

- **Email Reports**:
  - HTML-formatted daily reports
  - Visual indicators for items ending soon
  - "New" badges for first-time matches
  - High-discount highlighting

- **Automation**:
  - GitHub Actions workflow for daily execution
  - SQLite database for historical tracking
  - Graceful error handling

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/your-username/auction-monitor.git
cd auction-monitor

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Configuration

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Required for semantic matching
ANTHROPIC_API_KEY=your_api_key_here

# Email settings
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_RECIPIENT=recipient@example.com
```

### 3. Define Your Searches

Edit `searches.json` to add your search queries:

```json
{
  "searches": [
    {
      "id": "search-001",
      "query": "office chair with mesh seat",
      "active": true,
      "created_at": "2025-01-01T00:00:00Z"
    },
    {
      "id": "search-002",
      "query": "standing desk",
      "active": true,
      "created_at": "2025-01-01T00:00:00Z"
    }
  ]
}
```

Set `"active": false` to disable a search without deleting it.

### 4. Run the Monitor

```bash
# Run full pipeline
python -m src.main

# Run with options
python -m src.main --skip-email --log-level DEBUG

# View all options
python -m src.main --help
```

## CLI Options

```
usage: python -m src.main [-h] [--searches SEARCHES] [--database DATABASE]
                          [--log-level {DEBUG,INFO,WARNING,ERROR}]
                          [--log-file LOG_FILE] [--threshold THRESHOLD]
                          [--skip-scraping] [--skip-matching] [--skip-email]

Options:
  --searches, -s      Path to searches.json (default: searches.json)
  --database, -d      Path to SQLite database (default: auction_data.db)
  --log-level, -l     Logging level (default: INFO)
  --log-file          Path to log file (default: logs/monitor.log)
  --threshold, -t     Minimum relevance score 0-100 (default: 70)
  --skip-scraping     Skip web scraping (use existing data)
  --skip-matching     Skip semantic matching
  --skip-email        Skip sending email report
```

## GitHub Actions Setup

The included workflow runs daily at 10 AM UTC. To enable:

1. Go to your repository Settings > Secrets and variables > Actions
2. Add these secrets:
   - `ANTHROPIC_API_KEY`
   - `EMAIL_SMTP_HOST`
   - `EMAIL_SMTP_PORT`
   - `EMAIL_USER`
   - `EMAIL_PASSWORD`
   - `EMAIL_RECIPIENT`

3. Enable Actions in your repository

You can also trigger runs manually from the Actions tab.

## Project Structure

```
auction-monitor/
├── src/
│   ├── __init__.py
│   ├── main.py              # CLI entry point
│   ├── database.py          # SQLite operations
│   ├── matching.py          # Claude semantic matching
│   ├── email_report.py      # HTML email generation
│   └── scrapers/
│       ├── __init__.py
│       ├── base.py          # Base scraper class
│       ├── capital_city.py  # Capital City scraper
│       └── bidfta.py        # BidFTA scraper
├── tests/
│   ├── test_database.py
│   ├── test_email_report.py
│   └── test_scrapers.py
├── .github/workflows/
│   └── daily-monitor.yml    # GitHub Actions workflow
├── searches.json            # Search configuration
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

## Database Schema

The SQLite database tracks all items and matches:

- **items**: Auction items with details (price, condition, pickup, etc.)
- **images**: Image URLs associated with items
- **match_metadata**: Semantic matching results (score, reasoning)

Items are tracked historically with `first_seen` and `last_seen` dates.

## Semantic Matching

The matching system uses Claude to:

1. Analyze item title, description, and images
2. Compare against your search query
3. Score relevance (0-100)
4. Provide reasoning for the score

Items scoring 70+ are included in reports (configurable via `--threshold`).

### Avoiding False Positives

The system is tuned to avoid false positives. For example, searching for "stainless steel pan" will match cooking pans but filter out:
- Washer/dryer drip pans
- AC drain pans
- Oil pans

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_database.py -v
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | - | Claude API key (required for matching) |
| `EMAIL_SMTP_HOST` | No | smtp.gmail.com | SMTP server hostname |
| `EMAIL_SMTP_PORT` | No | 587 | SMTP server port |
| `EMAIL_USER` | No | - | SMTP username/email |
| `EMAIL_PASSWORD` | No | - | SMTP password/app password |
| `EMAIL_RECIPIENT` | No | - | Where to send reports |
| `RELEVANCE_THRESHOLD` | No | 70 | Minimum match score |
| `RATE_LIMIT_DELAY` | No | 0.5 | Seconds between requests |
| `LOG_LEVEL` | No | INFO | Logging verbosity |

*Required for semantic matching. Scraping works without it.

## Troubleshooting

### Scraping Issues

- **403/Blocked**: Sites may block aggressive scraping. The tool uses a standard browser User-Agent and rate limiting.
- **Timeouts**: Increase timeout with custom ScraperConfig if pages load slowly.
- **Missing Data**: Check logs for selector issues. Sites may change their HTML structure.

### Email Issues

- **Gmail**: Use an App Password, not your regular password. Enable 2FA first.
- **Authentication Failed**: Verify SMTP host/port match your provider.

### Matching Issues

- **Low Scores**: Try rephrasing your search query to be more specific.
- **API Errors**: Check your Anthropic API key and quota.

## License

MIT License - see LICENSE file for details.
