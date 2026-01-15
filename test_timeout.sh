#!/bin/bash
# Quick test script for timeout behavior
# Sets max_runtime to 1 minute instead of 28 for fast iteration
#
# USAGE:
#   ./test_timeout.sh
#
# WHAT IT DOES:
#   - Sets MAX_RUNTIME_MINUTES=1 to trigger timeout after 1 minute
#   - Runs the full workflow locally with --skip-email flag
#   - Generates LATEST_RESULTS.md with workflow status and errors
#   - Much faster than waiting 30 minutes for GitHub Actions
#
# WHAT TO CHECK AFTER RUNNING:
#   1. Check LATEST_RESULTS.md - should show workflow status (success/partial/timeout/failed)
#   2. Check that errors are listed in the report
#   3. Check that report timestamp updated
#   4. If workflow runs > 1 minute, should show "⏱️ Status: Workflow timed out"
#
# TROUBLESHOOTING:
#   - If you see Playwright errors, that's expected locally (browsers not installed)
#   - The important part is that the report is generated with error messages
#   - To test actual scraping, you need Playwright browsers: playwright install chromium

echo "🧪 Testing timeout behavior with 1-minute limit..."
echo "This simulates what happens when workflow approaches timeout"
echo ""

# Set a very short timeout for testing (1 minute instead of 28)
export MAX_RUNTIME_MINUTES=1

# Run the workflow
# It will timeout quickly and generate a report
python -m src.main --skip-email

echo ""
echo "✅ Test complete! Check LATEST_RESULTS.md to see the report."
echo "Expected: Report should show workflow status and any errors encountered."
echo ""
echo "To test actual timeout behavior (workflow stops at 1 min):"
echo "  - Install Playwright: playwright install chromium"
echo "  - Re-run this script - workflow should stop at ~1 min and show timeout status"
