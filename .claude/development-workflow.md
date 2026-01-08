# Development Workflow

## MANDATORY: Test Before Committing

**CRITICAL RULE:** Always test code changes locally BEFORE committing and pushing.

### Testing Commands

Use these commands to test without running the full workflow or incurring API costs:

```bash
# Test report generation only (no scraping/matching, no API calls)
python -m src.main --skip-scraping --skip-matching

# Test scraping only (no matching, no API calls)
python -m src.main --skip-matching

# Test matching only (no scraping, uses API - be careful!)
python -m src.main --skip-scraping

# Full run (scraping + matching, uses API - expensive!)
python -m src.main
```

### Standard Workflow

1. **Write code changes**
2. **Test locally first** using appropriate `--skip-*` flags above
3. **Verify output**
   - Check `LATEST_RESULTS.md` for report changes
   - Review console logs for errors
   - Confirm expected behavior
4. **Only then commit and push**

### Why This Matters

- **Catches bugs before CI** - Saves time waiting for GitHub Actions
- **Saves API costs** - Can test report generation without semantic matching
- **Faster iteration** - Local tests complete in seconds vs minutes
- **Better debugging** - Can add breakpoints and detailed logging locally

### Examples

**Testing timezone changes:**
```bash
python -m src.main --skip-scraping --skip-matching
# Then check: head -5 LATEST_RESULTS.md
```

**Testing scraper changes:**
```bash
python -m src.main --skip-matching
# Scrapes real sites but skips expensive AI matching
```

**Testing semantic matching changes:**
```bash
python -m src.main --skip-scraping
# Uses existing database items, only runs matching
```

## Project Context

- **Language**: Python 3.11+ with asyncio
- **Key Dependencies**: Playwright (browser automation), Anthropic API, aiosqlite
- **API Model**: Claude 3.5 Haiku (cost-optimized)
- **Deployment**: GitHub Actions daily workflow
- **Report Format**: Markdown committed to repo (for mobile viewing)
