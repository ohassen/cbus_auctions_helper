"""Generate Markdown report for viewing in GitHub."""

import logging
from datetime import datetime
from pathlib import Path
import pytz

from .database import Database

logger = logging.getLogger(__name__)


async def generate_markdown_report(
    db: Database,
    output_path: str = "LATEST_RESULTS.md",
    threshold: int = 70,
    workflow_errors: list[str] = None,
    workflow_status: str = "completed"
) -> bool:
    """Generate a Markdown report of all matches.

    Args:
        db: Database instance
        output_path: Path to write report to
        threshold: Minimum relevance score
        workflow_errors: List of error messages from workflow (if any)
        workflow_status: Status of workflow ("completed", "partial", "failed", "timeout")
    """

    try:
        # Get all matches (only unreported items)
        matches = await db.get_matches_for_report(threshold)

        # Get database stats
        stats = await db.get_stats()

        # Get per-search statistics
        search_stats = await db.get_search_statistics(threshold)

        # Generate Markdown
        markdown = _build_markdown(
            matches,
            stats,
            search_stats,
            threshold,
            workflow_errors or [],
            workflow_status
        )

        # Write to file
        output_file = Path(output_path)
        output_file.write_text(markdown, encoding='utf-8')

        # Mark all displayed items as reported
        if matches:
            item_ids = [m['id'] for m in matches]
            await db.mark_items_as_reported(item_ids)
            logger.info(f"Marked {len(item_ids)} items as reported")

        logger.info(f"Markdown report generated: {output_path} ({len(matches)} matches)")
        return True

    except Exception as e:
        logger.error(f"Failed to generate Markdown report: {e}")
        return False


def _build_markdown(
    matches: list,
    stats: dict,
    search_stats: dict,
    threshold: int,
    errors: list[str],
    status: str
) -> str:
    """Build the Markdown report."""

    # Use Eastern timezone
    eastern = pytz.timezone("America/New_York")
    now = datetime.now(eastern).strftime("%Y-%m-%d %I:%M %p %Z")

    # Group matches by search query
    grouped = {}
    for match in matches:
        query = match.get('search_query', 'Unknown')
        if query not in grouped:
            grouped[query] = []
        grouped[query].append(match)

    # Build header
    md = f"""# 🏷️ Auction Monitor Results

**Last Updated:** {now}

"""

    # Workflow Status Section
    md += "## 📋 Workflow Status\n\n"

    if status == "completed" and not errors:
        md += "✅ **Status:** Completed successfully\n\n"
    elif status == "partial" or (status == "completed" and errors):
        md += "⚠️ **Status:** Completed with errors\n\n"
        if errors:
            md += "**Errors encountered:**\n"
            for error in errors:
                md += f"- {error}\n"
            md += "\n"
    elif status == "timeout":
        md += "⏱️ **Status:** Workflow timed out (30-minute limit)\n\n"
        md += "*Report shows partial results from before timeout.*\n\n"
        if errors:
            md += "**Errors before timeout:**\n"
            for error in errors:
                md += f"- {error}\n"
            md += "\n"
    elif status == "failed":
        md += "❌ **Status:** Workflow failed\n\n"
        if errors:
            md += "**Errors:**\n"
            for error in errors:
                md += f"- {error}\n"
            md += "\n"

    md += "---\n\n"

    # Statistics Section
    md += f"""## 📊 Overall Statistics

- **Total Matches Found:** {len(matches)} (Score ≥ {threshold})
- **Items Seen Today:** {stats.get('items_seen_today', 0)}
- **Total Items Tracked (DB):** {stats.get('total_items', 0)}

---

## 🔍 Search Results

"""

    # Build sections for ALL searches (even with 0 matches)
    if search_stats:
        for query, query_stats in search_stats.items():
            total_scraped = query_stats.get('total_scraped', 0)
            by_source = query_stats.get('by_source', {})

            # Use the actual display list as the matched count — this is always
            # consistent with the links shown below (no "Matched: 3" + "No matches" contradiction)
            display_matches = grouped.get(query, [])
            matched = len(display_matches)

            md += f"### {query}\n\n"
            md += f"📥 **Items Scraped:** {total_scraped} | ✅ **Matched:** {matched}\n\n"

            # Show source breakdown if multiple sources
            if by_source:
                sources_str = " | ".join([f"{source}: {count}" for source, count in sorted(by_source.items())])
                md += f"*Sources: {sources_str}*\n\n"

            # Show matches for this query if any exist
            if display_matches:
                for item in grouped[query]:
                    md += _build_item_section(item)
                    md += "\n---\n\n"
            else:
                md += "*No matches found for this search*\n\n"

            md += "---\n\n"
    else:
        md += "No active searches configured.\n\n"

    md += f"\n*Powered by Claude AI semantic matching*\n"

    return md


def _build_item_section(item: dict) -> str:
    """Build Markdown for a single item."""

    title = item.get('title', 'Unknown Item')
    price = item.get('current_price')
    msrp = item.get('msrp')
    discount_pct = item.get('discount_pct', 0)
    score = item.get('relevance_score', 0)
    condition = item.get('condition', 'Unknown')
    auction_end = item.get('auction_end', '')
    pickup_location = item.get('pickup_location', '')
    url = item.get('listing_url', '#')
    is_new = item.get('is_new', False)
    source = item.get('source_site', 'unknown')

    # Format price
    price_str = f"${price:.2f}" if price else "No bids yet"

    # Build badges
    badges = []
    if is_new:
        badges.append("🆕 NEW")
    if score >= 85:
        badges.append(f"⭐ {score}% Match")
    elif score >= 70:
        badges.append(f"✓ {score}% Match")
    if discount_pct and discount_pct > 50:
        badges.append(f"🔥 {int(discount_pct)}% OFF")

    badges_str = " ".join(badges) if badges else ""

    # Build item section
    md = f"### {title}\n\n"

    if badges_str:
        md += f"{badges_str}\n\n"

    md += f"**[🔗 View Auction]({url})**\n\n"

    # Price info
    md += f"**Current Price:** {price_str}\n\n"
    if msrp and msrp > 0 and discount_pct is not None:
        md += f"**Retail Price:** ~~${msrp:.2f}~~ (Save {int(discount_pct)}%)\n\n"

    # Details
    details = []
    if condition:
        details.append(f"**Condition:** {condition}")
    if auction_end:
        try:
            end_date = datetime.fromisoformat(auction_end.replace('Z', '+00:00'))
            details.append(f"**Ends:** {end_date.strftime('%b %d, %I:%M %p')}")
        except:
            details.append(f"**Ends:** {auction_end}")
    if pickup_location:
        details.append(f"📍 **Pickup:** {pickup_location}")
    details.append(f"**Source:** {source}")

    md += "\n\n".join(details) + "\n\n"

    return md
