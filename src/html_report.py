"""Generate HTML report for GitHub Pages."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .database import Database

logger = logging.getLogger(__name__)


async def generate_html_report(
    db: Database,
    output_path: str = "docs/index.html",
    threshold: int = 70
) -> bool:
    """Generate an HTML report of all matches and save to file."""

    try:
        # Get all matches
        matches = await db.get_matches_for_report(threshold)

        # Get database stats
        stats = await db.get_stats()

        # Generate HTML
        html = _build_html(matches, stats, threshold)

        # Ensure output directory exists
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Write to file
        output_file.write_text(html, encoding='utf-8')

        logger.info(f"HTML report generated: {output_path} ({len(matches)} matches)")
        return True

    except Exception as e:
        logger.error(f"Failed to generate HTML report: {e}")
        return False


def _build_html(matches: list, stats: dict, threshold: int) -> str:
    """Build the HTML report."""

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")

    # Group matches by search query
    grouped = {}
    for match in matches:
        query = match.get('search_query', 'Unknown')
        if query not in grouped:
            grouped[query] = []
        grouped[query].append(match)

    # Build match sections
    match_html = ""
    if grouped:
        for query, items in grouped.items():
            match_html += f"""
    <div class="search-section">
        <h2>🔍 {query}</h2>
        <p class="count">{len(items)} match{"es" if len(items) != 1 else ""} found</p>
        <div class="items">
"""
            for item in items:
                match_html += _build_item_card(item)

            match_html += """
        </div>
    </div>
"""
    else:
        match_html = """
    <div class="no-results">
        <p>😴 No matches found yet. Check back tomorrow!</p>
    </div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Auction Monitor Results</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}

        h1 {{
            color: #2c3e50;
            margin-bottom: 10px;
        }}

        .meta {{
            color: #7f8c8d;
            font-size: 14px;
        }}

        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}

        .stat {{
            background: #ecf0f1;
            padding: 15px;
            border-radius: 8px;
        }}

        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
        }}

        .stat-label {{
            font-size: 12px;
            color: #7f8c8d;
            text-transform: uppercase;
        }}

        .search-section {{
            margin-bottom: 40px;
        }}

        .search-section h2 {{
            color: #2c3e50;
            margin-bottom: 10px;
        }}

        .count {{
            color: #7f8c8d;
            margin-bottom: 20px;
        }}

        .items {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 20px;
        }}

        .item-card {{
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .item-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        }}

        .item-image {{
            width: 100%;
            height: 200px;
            object-fit: cover;
            background: #ecf0f1;
        }}

        .item-content {{
            padding: 20px;
        }}

        .item-title {{
            font-size: 16px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 10px;
            line-height: 1.4;
        }}

        .item-meta {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }}

        .price {{
            font-size: 20px;
            font-weight: bold;
            color: #27ae60;
        }}

        .badge {{
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}

        .badge.new {{
            background: #3498db;
            color: white;
        }}

        .badge.discount {{
            background: #e74c3c;
            color: white;
        }}

        .badge.score {{
            background: #95a5a6;
            color: white;
        }}

        .item-details {{
            font-size: 14px;
            color: #7f8c8d;
            margin-bottom: 15px;
        }}

        .item-details p {{
            margin-bottom: 5px;
        }}

        .item-link {{
            display: block;
            text-align: center;
            background: #3498db;
            color: white;
            padding: 12px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            transition: background 0.2s;
        }}

        .item-link:hover {{
            background: #2980b9;
        }}

        .no-results {{
            background: white;
            padding: 60px;
            text-align: center;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .no-results p {{
            font-size: 18px;
            color: #7f8c8d;
        }}

        footer {{
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            color: #7f8c8d;
            font-size: 14px;
        }}

        @media (max-width: 768px) {{
            .items {{
                grid-template-columns: 1fr;
            }}

            .stats {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🏷️ Auction Monitor</h1>
            <p class="meta">Last updated: {now}</p>

            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{len(matches)}</div>
                    <div class="stat-label">Matches (Score ≥{threshold})</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{stats.get('total_items', 0)}</div>
                    <div class="stat-label">Total Items Scraped</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{stats.get('items_seen_today', 0)}</div>
                    <div class="stat-label">Items Seen Today</div>
                </div>
            </div>
        </header>

        {match_html}

        <footer>
            <p>Automatically updated daily by GitHub Actions</p>
            <p>Powered by Claude AI semantic matching</p>
        </footer>
    </div>
</body>
</html>"""


def _build_item_card(item: dict) -> str:
    """Build HTML for a single item card."""

    # Extract item details
    title = item.get('title', 'Unknown Item')
    price = item.get('current_price')
    msrp = item.get('msrp')
    discount_pct = item.get('discount_pct', 0)
    score = item.get('relevance_score', 0)
    condition = item.get('condition', 'Unknown')
    auction_end = item.get('auction_end', '')
    pickup_location = item.get('pickup_location', '')
    url = item.get('listing_url', '#')
    image_url = item.get('image_urls', [''])[0] if item.get('image_urls') else ''
    is_new = item.get('is_new', False)
    source = item.get('source_site', 'unknown')

    # Format price
    price_html = f"${price:.2f}" if price else "No bids yet"

    # Build badges
    badges = []
    if is_new:
        badges.append('<span class="badge new">NEW</span>')
    if score >= 80:
        badges.append(f'<span class="badge score">Match: {score}%</span>')
    if discount_pct and discount_pct > 50:
        badges.append(f'<span class="badge discount">-{int(discount_pct)}%</span>')

    badges_html = " ".join(badges)

    # Format MSRP line
    msrp_html = ""
    if msrp and msrp > 0:
        msrp_html = f"<p>Retail: <s>${msrp:.2f}</s></p>"

    # Format auction end
    end_html = ""
    if auction_end:
        try:
            end_date = datetime.fromisoformat(auction_end.replace('Z', '+00:00'))
            end_html = f"<p>Ends: {end_date.strftime('%b %d, %I:%M %p')}</p>"
        except:
            end_html = f"<p>Ends: {auction_end}</p>"

    # Format pickup
    pickup_html = ""
    if pickup_location:
        pickup_html = f"<p>📍 {pickup_location}</p>"

    # Image
    image_html = ""
    if image_url:
        image_html = f'<img src="{image_url}" alt="{title}" class="item-image" loading="lazy">'
    else:
        image_html = '<div class="item-image" style="display:flex;align-items:center;justify-content:center;color:#95a5a6;">No Image</div>'

    return f"""
            <div class="item-card">
                {image_html}
                <div class="item-content">
                    <h3 class="item-title">{title}</h3>

                    <div class="item-meta">
                        <span class="price">{price_html}</span>
                        <div>{badges_html}</div>
                    </div>

                    <div class="item-details">
                        {msrp_html}
                        <p>Condition: {condition}</p>
                        {end_html}
                        {pickup_html}
                        <p style="font-size:12px;color:#95a5a6;">Source: {source}</p>
                    </div>

                    <a href="{url}" target="_blank" class="item-link">View Auction →</a>
                </div>
            </div>
"""
