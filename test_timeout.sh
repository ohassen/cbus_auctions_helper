#!/bin/bash
# Quick test script for timeout behavior
# Sets max_runtime to 1 minute instead of 28 for fast iteration

echo "Testing timeout behavior with 1-minute limit..."
echo "This simulates what happens when workflow approaches timeout"
echo ""

# Set a very short timeout for testing (1 minute instead of 28)
export MAX_RUNTIME_MINUTES=1

# Run the workflow
# It will timeout quickly and generate a report
python -m src.main --skip-email

echo ""
echo "Test complete! Check LATEST_RESULTS.md to see the timeout report."
echo "The workflow should have stopped at ~1 minute and generated a report."
