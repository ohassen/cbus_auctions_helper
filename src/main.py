#!/usr/bin/env python3
"""
Auction Monitor CLI - Main orchestration script.

Monitors auction websites for specific items, uses AI semantic matching,
and sends email reports with matches.
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .database import Database, AuctionItem, MatchMetadata, load_searches
from .scrapers import CapitalCityScraper, BidFTAScraper
from .scrapers.base import ScraperConfig
from .matching import SemanticMatcher, MatchResult
from .email_report import EmailConfig, generate_report_html, send_email_report, send_error_report

# Load environment variables
load_dotenv()

# Configure logging
def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Configure logging for the application."""
    handlers = [logging.StreamHandler()]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path))

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers
    )


logger = logging.getLogger(__name__)


async def scrape_site(scraper_class, config: ScraperConfig, searches: list, db: Database) -> dict:
    """Scrape a single auction site for all search queries."""
    results = {
        "site": scraper_class.name if hasattr(scraper_class, 'name') else scraper_class.__name__,
        "items_scraped": 0,
        "errors": []
    }

    try:
        async with scraper_class(config) as scraper:
            for search in searches:
                logger.info(f"Searching {scraper.name} for: {search.query}")
                try:
                    items = await scraper.scrape_all(search.query, search.id)
                    logger.info(f"{scraper.name}: Found {len(items)} items for '{search.query}'")
                    results["items_scraped"] += len(items)

                    # Save items to database
                    for item in items:
                        await db.upsert_item(item)

                except Exception as e:
                    error_msg = f"Error searching '{search.query}': {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)

    except Exception as e:
        error_msg = f"Failed to initialize scraper: {str(e)}"
        logger.error(error_msg)
        results["errors"].append(error_msg)

    return results


async def run_semantic_matching(db: Database, matcher: SemanticMatcher, searches: list) -> int:
    """Run semantic matching on all scraped items."""
    from datetime import date
    today = date.today().isoformat()

    total_matches = 0

    for search in searches:
        logger.info(f"Running semantic matching for: {search.query}")

        # Get items scraped today for this search
        cursor = await db._connection.execute("""
            SELECT * FROM items WHERE search_id = ? AND last_seen = ?
        """, (search.id, today))
        rows = await cursor.fetchall()

        if not rows:
            logger.info(f"No items to match for search: {search.query}")
            continue

        # Convert to AuctionItem objects
        items = []
        for row in rows:
            item_dict = dict(row)
            # Get images
            img_cursor = await db._connection.execute(
                "SELECT url FROM images WHERE item_id = ?", (row["id"],)
            )
            images = await img_cursor.fetchall()
            item_dict["image_urls"] = [img["url"] for img in images]

            item = AuctionItem(
                id=item_dict["id"],
                search_id=item_dict["search_id"],
                source_site=item_dict["source_site"],
                external_id=item_dict["external_id"],
                title=item_dict["title"],
                description=item_dict.get("description", ""),
                current_price=item_dict.get("current_price"),
                msrp=item_dict.get("msrp"),
                discount_pct=item_dict.get("discount_pct"),
                condition=item_dict.get("condition", ""),
                auction_end=item_dict.get("auction_end"),
                pickup_location=item_dict.get("pickup_location", ""),
                pickup_dates=item_dict.get("pickup_dates", ""),
                listing_url=item_dict["listing_url"],
                image_urls=item_dict.get("image_urls", [])
            )
            items.append(item)

        logger.info(f"Evaluating {len(items)} items for '{search.query}'")

        # Process items in batches
        for i, item in enumerate(items):
            try:
                result = await matcher.evaluate_item(search.query, item)

                if result.is_match:
                    # Save match metadata
                    metadata = MatchMetadata(
                        item_id=item.id,
                        relevance_score=result.relevance_score,
                        reasoning=result.reasoning,
                        confidence=result.confidence
                    )
                    await db.save_match_metadata(metadata)
                    total_matches += 1
                    logger.info(f"Match found: {item.title[:50]}... (score: {result.relevance_score})")

                # Rate limiting
                if i < len(items) - 1:
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error matching item {item.title[:50]}: {e}")

    return total_matches


async def lookup_missing_msrp(db: Database, matcher: SemanticMatcher) -> int:
    """Look up MSRP for items that don't have it."""
    items = await db.get_items_needing_msrp()

    if not items:
        return 0

    logger.info(f"Looking up MSRP for {len(items)} items")
    updated = 0

    for item_dict in items:
        item = AuctionItem(
            id=item_dict["id"],
            title=item_dict["title"],
            description=item_dict.get("description", ""),
            current_price=item_dict.get("current_price")
        )

        try:
            result = await matcher.lookup_msrp(item)
            if result.msrp:
                # Calculate discount
                discount_pct = None
                if item.current_price and result.msrp > 0:
                    discount_pct = round((result.msrp - item.current_price) / result.msrp * 100, 1)

                await db.update_item_msrp(item.id, result.msrp, discount_pct or 0)
                updated += 1
                logger.info(f"Updated MSRP for {item.title[:50]}: ${result.msrp:.2f}")

            await asyncio.sleep(0.5)  # Rate limiting

        except Exception as e:
            logger.error(f"Error looking up MSRP for {item.title[:50]}: {e}")

    return updated


async def run_monitor(
    searches_path: str = "searches.json",
    db_path: str = "auction_data.db",
    skip_scraping: bool = False,
    skip_matching: bool = False,
    skip_email: bool = False,
    relevance_threshold: int = 70
) -> dict:
    """Run the complete monitoring pipeline."""

    results = {
        "start_time": datetime.now(),
        "searches": 0,
        "items_scraped": 0,
        "matches_found": 0,
        "email_sent": False,
        "errors": []
    }

    # Load searches
    searches = load_searches(searches_path)
    if not searches:
        logger.warning("No active searches found")
        return results

    results["searches"] = len(searches)
    logger.info(f"Loaded {len(searches)} active searches")

    # Initialize database
    async with Database(db_path) as db:
        # Phase 1: Scraping
        if not skip_scraping:
            logger.info("=" * 50)
            logger.info("PHASE 1: Web Scraping")
            logger.info("=" * 50)

            scraper_config = ScraperConfig(
                rate_limit_delay=float(os.getenv("RATE_LIMIT_DELAY", "0.5")),
                headless=True
            )

            # Scrape Capital City Online Auction
            logger.info("Scraping Capital City Online Auction...")
            cc_results = await scrape_site(CapitalCityScraper, scraper_config, searches, db)
            results["items_scraped"] += cc_results["items_scraped"]
            results["errors"].extend(cc_results["errors"])

            # Scrape BidFTA
            logger.info("Scraping BidFTA (Columbus locations)...")
            bidfta_results = await scrape_site(BidFTAScraper, scraper_config, searches, db)
            results["items_scraped"] += bidfta_results["items_scraped"]
            results["errors"].extend(bidfta_results["errors"])

            logger.info(f"Total items scraped: {results['items_scraped']}")

        # Phase 2: Semantic Matching
        if not skip_matching and os.getenv("ANTHROPIC_API_KEY"):
            logger.info("=" * 50)
            logger.info("PHASE 2: Semantic Matching")
            logger.info("=" * 50)

            try:
                matcher = SemanticMatcher(
                    relevance_threshold=relevance_threshold
                )

                results["matches_found"] = await run_semantic_matching(db, matcher, searches)
                logger.info(f"Total matches found: {results['matches_found']}")

                # Look up MSRP for items without it
                updated = await lookup_missing_msrp(db, matcher)
                logger.info(f"Updated MSRP for {updated} items")

            except Exception as e:
                error_msg = f"Semantic matching failed: {str(e)}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        elif not os.getenv("ANTHROPIC_API_KEY"):
            logger.warning("ANTHROPIC_API_KEY not set, skipping semantic matching")

        # Mark ended auctions
        await db.mark_ended_auctions()

        # Phase 3: Email Report
        if not skip_email:
            logger.info("=" * 50)
            logger.info("PHASE 3: Email Report")
            logger.info("=" * 50)

            email_config = EmailConfig.from_env()

            # Debug logging for email config
            logger.info(f"Email config - Host: {email_config.smtp_host}, Port: {email_config.smtp_port}")
            logger.info(f"Email config - User set: {bool(email_config.username)}, Password set: {bool(email_config.password)}")
            logger.info(f"Email config - Recipient: {email_config.recipient[:20] + '...' if email_config.recipient else 'NOT SET'}")

            if email_config.username and email_config.password and email_config.recipient:
                # Get today's matches
                matches = await db.get_todays_matches(min_score=relevance_threshold)
                logger.info(f"Generating report for {len(matches)} matches")

                # Generate HTML report
                html = generate_report_html(matches)

                # Send email
                results["email_sent"] = send_email_report(
                    email_config,
                    html,
                    match_count=len(matches)
                )

                # Send error notifications if any
                if results["errors"]:
                    send_error_report(
                        email_config,
                        "\n".join(results["errors"]),
                        "Multiple Sites"
                    )
            else:
                logger.warning("Email not configured, skipping email report")

        # Phase 4: Generate Markdown Report
        logger.info("=" * 50)
        logger.info("PHASE 4: Markdown Report")
        logger.info("=" * 50)

        try:
            from .markdown_report import generate_markdown_report
            md_generated = await generate_markdown_report(db, threshold=relevance_threshold)
            if md_generated:
                logger.info("Markdown report generated successfully")
            else:
                logger.warning("Failed to generate Markdown report")
        except Exception as e:
            logger.error(f"Error generating Markdown report: {e}")
            results["errors"].append(f"Markdown report generation failed: {str(e)}")

        # Log stats
        stats = await db.get_stats()
        logger.info(f"Database stats: {stats}")

    results["end_time"] = datetime.now()
    results["duration"] = (results["end_time"] - results["start_time"]).total_seconds()

    return results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Auction Monitor CLI - Monitor auction sites for specific items"
    )

    parser.add_argument(
        "--searches", "-s",
        default="searches.json",
        help="Path to searches.json configuration file"
    )
    parser.add_argument(
        "--database", "-d",
        default="auction_data.db",
        help="Path to SQLite database file"
    )
    parser.add_argument(
        "--log-level", "-l",
        default=os.getenv("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )
    parser.add_argument(
        "--log-file",
        default="logs/monitor.log",
        help="Path to log file"
    )
    parser.add_argument(
        "--threshold", "-t",
        type=int,
        default=int(os.getenv("RELEVANCE_THRESHOLD", "70")),
        help="Minimum relevance score for matches (0-100)"
    )
    parser.add_argument(
        "--skip-scraping",
        action="store_true",
        help="Skip web scraping (use existing data)"
    )
    parser.add_argument(
        "--skip-matching",
        action="store_true",
        help="Skip semantic matching"
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="Skip sending email report"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level, args.log_file)

    logger.info("Starting Auction Monitor")
    logger.info(f"Searches config: {args.searches}")
    logger.info(f"Database: {args.database}")
    logger.info(f"Relevance threshold: {args.threshold}")

    # Run the monitor
    try:
        results = asyncio.run(run_monitor(
            searches_path=args.searches,
            db_path=args.database,
            skip_scraping=args.skip_scraping,
            skip_matching=args.skip_matching,
            skip_email=args.skip_email,
            relevance_threshold=args.threshold
        ))

        logger.info("=" * 50)
        logger.info("RESULTS SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Searches processed: {results['searches']}")
        logger.info(f"Items scraped: {results['items_scraped']}")
        logger.info(f"Matches found: {results['matches_found']}")
        logger.info(f"Email sent: {results['email_sent']}")
        logger.info(f"Duration: {results['duration']:.2f} seconds")

        if results["errors"]:
            logger.warning(f"Errors encountered: {len(results['errors'])}")
            for error in results["errors"]:
                logger.warning(f"  - {error}")

        sys.exit(0 if not results["errors"] else 1)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
