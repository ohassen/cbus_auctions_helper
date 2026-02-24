#!/usr/bin/env python3
"""
Auction Monitor CLI - Main orchestration script.

Monitors auction websites for specific items and uses AI semantic matching.
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
from .timeout_manager import TimeoutManager

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


async def scrape_site(scraper_class, config: ScraperConfig, searches: list, db: Database, max_items_per_search: Optional[int] = 12) -> dict:
    """Scrape a single auction site for all search queries.

    Args:
        max_items_per_search: Maximum items to scrape per search query (default: 12)
                             Set to None for unlimited (not recommended)
    """
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
                    items = await scraper.scrape_all(search.query, search.id, max_items=max_items_per_search)
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


async def run_semantic_matching(db: Database, matcher: SemanticMatcher, searches: list) -> tuple[int, int]:
    """Run semantic matching on all scraped items.

    Returns:
        Tuple of (total_matches, total_api_errors)
    """
    from datetime import date
    today = date.today().isoformat()

    total_matches = 0
    total_api_errors = 0

    for search in searches:
        logger.info(f"Running semantic matching for: {search.query}")

        # Get items scraped today that haven't been matched yet
        # Skip items that already have match_metadata to avoid re-matching on multiple runs
        cursor = await db._connection.execute("""
            SELECT * FROM items
            WHERE search_id = ? AND last_seen = ?
              AND id NOT IN (SELECT item_id FROM match_metadata)
        """, (search.id, today))
        rows = await cursor.fetchall()

        if not rows:
            logger.info(f"No new items to match for search: {search.query}")
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
        search_errors = 0
        for i, item in enumerate(items):
            try:
                result = await matcher.evaluate_item(search.query, item)

                # Check if the result indicates an API failure (score=0 with error reasoning)
                if result.reasoning and result.reasoning.startswith("Evaluation failed:"):
                    search_errors += 1
                    total_api_errors += 1
                    logger.error(f"API error evaluating '{item.title[:50]}': {result.reasoning}")
                elif result.is_match:
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
                search_errors += 1
                total_api_errors += 1
                logger.error(f"Error matching item {item.title[:50]}: {e}")

        if search_errors > 0:
            logger.warning(
                f"Matching '{search.query}': {search_errors}/{len(items)} items failed due to API errors. "
                f"Check that ANTHROPIC_API_KEY is valid and not expired."
            )

    return total_matches, total_api_errors


async def run_monitor(
    searches_path: str = "searches.json",
    db_path: str = "auction_data.db",
    skip_scraping: bool = False,
    skip_matching: bool = False,
    relevance_threshold: int = 70,
    max_runtime_minutes: int = None,
    max_items_per_search: int = 25
) -> dict:
    """Run the complete monitoring pipeline.

    Args:
        max_runtime_minutes: Maximum runtime before forcing stop (default 28 min to beat GitHub Actions 30 min timeout)
                            Can be overridden with MAX_RUNTIME_MINUTES environment variable
        max_items_per_search: Maximum items to scrape per search query (default: 25)
                             Increased from 12 to capture more results per search
    """

    # Allow environment variable to override default
    if max_runtime_minutes is None:
        max_runtime_minutes = int(os.getenv("MAX_RUNTIME_MINUTES", "28"))

    results = {
        "start_time": datetime.now(),
        "searches": 0,
        "items_scraped": 0,
        "matches_found": 0,
        "errors": [],
        "timed_out": False
    }

    # Load searches
    searches = load_searches(searches_path)
    if not searches:
        logger.warning("No active searches found")
        return results

    results["searches"] = len(searches)
    logger.info(f"Loaded {len(searches)} active searches")

    # Initialize timeout manager
    timeout_manager = TimeoutManager(max_minutes=max_runtime_minutes)
    timeout_manager.log_status("Start")

    # Initialize database
    async with Database(db_path) as db:
        try:
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
                logger.info(f"Scraping Capital City Online Auction (max {max_items_per_search} items per search)...")
                cc_results = await scrape_site(CapitalCityScraper, scraper_config, searches, db, max_items_per_search)
                results["items_scraped"] += cc_results["items_scraped"]
                results["errors"].extend(cc_results["errors"])

                # Check timeout before BidFTA
                if timeout_manager.is_approaching_timeout():
                    logger.warning("Approaching timeout, skipping BidFTA to ensure report generation")
                    results["timed_out"] = True
                    results["errors"].append(timeout_manager.get_timeout_message())
                else:
                    # Scrape BidFTA
                    logger.info(f"Scraping BidFTA (Columbus locations, max {max_items_per_search} items per search)...")
                    bidfta_results = await scrape_site(BidFTAScraper, scraper_config, searches, db, max_items_per_search)
                    results["items_scraped"] += bidfta_results["items_scraped"]
                    results["errors"].extend(bidfta_results["errors"])

                logger.info(f"Total items scraped: {results['items_scraped']}")

            # Phase 2: Semantic Matching
            if not skip_matching and os.getenv("ANTHROPIC_API_KEY") and not timeout_manager.is_approaching_timeout():
                logger.info("=" * 50)
                logger.info("PHASE 2: Semantic Matching")
                logger.info("=" * 50)

                try:
                    matcher = SemanticMatcher(
                        relevance_threshold=relevance_threshold
                    )

                    # Validate the API key with a minimal test call before processing all items
                    api_key_valid = await matcher.validate_api_key()
                    if not api_key_valid:
                        error_msg = (
                            "ANTHROPIC_API_KEY validation failed - key may be expired or invalid. "
                            "Go to console.anthropic.com to check your API key. "
                            "Semantic matching skipped."
                        )
                        logger.error(error_msg)
                        results["errors"].append(error_msg)
                    else:
                        matches_found, api_errors = await run_semantic_matching(db, matcher, searches)
                        results["matches_found"] = matches_found
                        logger.info(f"Total matches found: {results['matches_found']}")

                        if api_errors > 0:
                            error_msg = (
                                f"{api_errors} items failed semantic matching due to API errors. "
                                f"Check that ANTHROPIC_API_KEY is valid and not expired."
                            )
                            logger.error(error_msg)
                            results["errors"].append(error_msg)

                except Exception as e:
                    error_msg = f"Semantic matching failed: {str(e)}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
            elif timeout_manager.is_approaching_timeout():
                logger.warning("Approaching timeout, skipping semantic matching to ensure report generation")
                if not results["timed_out"]:
                    results["timed_out"] = True
                    results["errors"].append(timeout_manager.get_timeout_message())
            elif not os.getenv("ANTHROPIC_API_KEY"):
                logger.warning("ANTHROPIC_API_KEY not set, skipping semantic matching")

        except Exception as e:
            # Catch any unexpected errors in the main workflow
            error_msg = f"Workflow error: {str(e)}"
            logger.error(error_msg)
            results["errors"].append(error_msg)
        finally:
            # Mark ended auctions BEFORE generating report
            # This ensures sold/ended items are marked inactive before report shows them
            try:
                await db.mark_ended_auctions()
            except Exception as e:
                logger.warning(f"Failed to mark ended auctions: {e}")

            # Phase 4: Generate Markdown Report (ALWAYS runs, even if earlier phases fail)
            logger.info("=" * 50)
            logger.info("PHASE 4: Markdown Report")
            logger.info("=" * 50)

            # Determine workflow status
            workflow_status = "completed"
            if results["timed_out"]:
                workflow_status = "timeout"
            elif results["errors"]:
                if results["items_scraped"] == 0:
                    workflow_status = "failed"
                else:
                    workflow_status = "partial"

            try:
                from .markdown_report import generate_markdown_report
                md_generated = await generate_markdown_report(
                    db,
                    threshold=relevance_threshold,
                    workflow_errors=results["errors"],
                    workflow_status=workflow_status
                )
                if md_generated:
                    logger.info("Markdown report generated successfully")
                else:
                    logger.warning("Failed to generate Markdown report")
            except Exception as e:
                logger.error(f"Error generating Markdown report: {e}")
                results["errors"].append(f"Markdown report generation failed: {str(e)}")

            # Log stats
            try:
                stats = await db.get_stats()
                logger.info(f"Database stats: {stats}")
            except Exception as e:
                logger.warning(f"Could not get database stats: {e}")

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
            relevance_threshold=args.threshold
        ))

        logger.info("=" * 50)
        logger.info("RESULTS SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Searches processed: {results['searches']}")
        logger.info(f"Items scraped: {results['items_scraped']}")
        logger.info(f"Matches found: {results['matches_found']}")
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
