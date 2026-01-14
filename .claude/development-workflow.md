# Development Workflow

## MANDATORY: Test Before Committing

**CRITICAL RULE:** Always test code changes locally BEFORE committing and pushing.

### Special Rule: Performance/Timeout Changes

**FOR TIMEOUT/PERFORMANCE CHANGES:** ALWAYS calculate timing FIRST, then implement:

1. **Calculate expected timing** using Python script with new parameters
2. **Verify it fits within 30-minute GitHub Actions limit**
3. **Document the calculation in the commit message**
4. **Then implement the changes**

Example timing calculation script:
```python
searches = 4
items_per_search = 8  # Your new value
seconds_per_item = 19.5  # goto + sleep + processing

per_search_time = (page_scan_time + items_per_search * seconds_per_item) / 60
total_time = per_search_time * searches + matching_time

print(f"Total: {total_time:.1f} minutes")
print(f"Status: {'✓ PASS' if total_time <= 30 else '✗ FAIL'}")
```

**DO NOT commit timeout changes without calculating timing first.**

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

1. **Plan the change**
   - For timeout/performance changes: Calculate timing FIRST (see above)
   - For scraper changes: Understand current behavior before modifying

2. **Write code changes**

3. **Test locally first** using appropriate `--skip-*` flags above
   - Timeout changes: Run timing calculation script to verify
   - Scraper changes: Run with `--skip-matching` flag
   - Report changes: Run with `--skip-scraping --skip-matching`

4. **Verify output**
   - Check `LATEST_RESULTS.md` for report changes
   - Review console logs for errors
   - Confirm expected behavior
   - For timeout changes: Verify calculation matches actual timing

5. **Only then commit and push**
   - Include calculation results in commit message for timeout changes
   - Reference which test command was used

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

## Common Mistakes to Avoid

### ❌ DON'T: Commit timeout changes without calculating timing first
**Example:** Changing `max_items=30` to `max_items=15` without calculating if 15 items × 4 searches fits in 30 minutes.

**Result:** Workflow still times out because you didn't account for per-item processing time.

### ✅ DO: Calculate first, implement second
1. Write timing calculation script with proposed values
2. Verify total time < 30 minutes with buffer
3. Implement the changes
4. Include calculation in commit message

### ❌ DON'T: Test "in production" (via GitHub Actions)
**Example:** Push changes and wait 30 minutes for workflow to run to see if it works.

**Result:** Wastes time, API credits, and requires multiple failed runs to debug.

### ✅ DO: Test locally with skip flags first
```bash
# Test without API costs or long waits
python -m src.main --skip-matching
```

### ❌ DON'T: Make multiple changes at once without testing
**Example:** Reduce items, change timeouts, modify page scanning - all in one commit without testing any of it.

**Result:** When it fails, you don't know which change caused the problem.

### ✅ DO: Make incremental changes with testing between each
1. Change one parameter
2. Calculate/test
3. Commit if it works
4. Then make next change

## Project Context

- **Language**: Python 3.11+ with asyncio
- **Key Dependencies**: Playwright (browser automation), Anthropic API, aiosqlite
- **API Model**: Claude 3.5 Haiku (cost-optimized)
- **Deployment**: GitHub Actions daily workflow (30-minute timeout limit)
- **Report Format**: Markdown committed to repo (for mobile viewing)
- **Critical Constraint**: Must complete within 30 minutes (GitHub Actions limit)
