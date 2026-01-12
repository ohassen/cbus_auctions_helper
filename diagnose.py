#!/usr/bin/env python3
"""Diagnostic script to check workflow status."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database

async def diagnose():
    """Check database state and report what would be shown."""

    db_path = "auction_data.db"

    if not Path(db_path).exists():
        print("❌ No database file found")
        print("This means scraping hasn't run yet or failed completely")
        return

    async with Database(db_path) as db:
        # Get overall stats
        stats = await db.get_stats()
        print("📊 Database Stats:")
        print(f"  Total items: {stats.get('total_items', 0)}")
        print(f"  Active items: {stats.get('active_items', 0)}")
        print(f"  Items seen today: {stats.get('items_seen_today', 0)}")
        print()

        # Check for unreported matches
        matches = await db.get_matches_for_report(threshold=70)
        print(f"📝 Report Status:")
        print(f"  Unreported matches (≥70%): {len(matches)}")

        if matches:
            print("\n  Items that WILL appear in next report:")
            for m in matches[:5]:
                print(f"    - {m['title'][:60]} ({m['relevance_score']}%)")
        else:
            print("  ⚠️  No unreported matches - report won't change!")
        print()

        # Check all items (including reported)
        cursor = await db._connection.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN reported_at IS NULL THEN 1 ELSE 0 END) as unreported
            FROM items i
            JOIN match_metadata m ON i.id = m.item_id
            WHERE i.is_active = 1 AND m.relevance_score >= 70
        """)
        row = await cursor.fetchone()

        print(f"🔍 All Matches:")
        print(f"  Total matches: {row['total']}")
        print(f"  Already reported: {row['total'] - row['unreported']}")
        print(f"  Unreported: {row['unreported']}")
        print()

        # Check recent scraping activity
        cursor = await db._connection.execute("""
            SELECT
                source_site,
                COUNT(*) as count,
                MAX(last_seen) as last_seen
            FROM items
            GROUP BY source_site
        """)
        rows = await cursor.fetchall()

        print(f"🌐 Scraping Activity:")
        for row in rows:
            print(f"  {row['source_site']}: {row['count']} items (last seen: {row['last_seen']})")
        print()

        # Diagnosis
        print("💡 Diagnosis:")
        if stats.get('items_seen_today', 0) == 0:
            print("  ⚠️  No items scraped today - scraping may have failed")
        elif row['unreported'] == 0 and row['total'] > 0:
            print("  ℹ️  All matches already reported - waiting for new items")
        elif row['total'] == 0:
            print("  ⚠️  No items match the 70% threshold - items scraped but not relevant")
        else:
            print("  ✓ Everything looks normal")

if __name__ == "__main__":
    asyncio.run(diagnose())
