"""Tests for the database module."""

import asyncio
import os
import tempfile
from datetime import date, datetime
from unittest.mock import patch

import pytest
import pytest_asyncio

from src.database import Database, AuctionItem, MatchMetadata, load_searches


@pytest_asyncio.fixture
async def db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()
    os.unlink(db_path)


@pytest.fixture
def sample_item():
    """Create a sample auction item for testing."""
    return AuctionItem(
        search_id="test-search-001",
        source_site="test_site",
        external_id="12345",
        title="Test Office Chair with Mesh Seat",
        description="Ergonomic office chair with breathable mesh back and seat",
        current_price=45.00,
        msrp=199.99,
        discount_pct=77.5,
        condition="Like New",
        auction_end=datetime(2025, 1, 15, 14, 0, 0),
        pickup_location="Columbus, OH 43215",
        pickup_dates="Jan 16-17, 9AM-5PM",
        listing_url="https://example.com/lot/12345",
        image_urls=["https://example.com/images/12345-1.jpg", "https://example.com/images/12345-2.jpg"]
    )


@pytest.mark.asyncio
async def test_database_init(db):
    """Test database initializes correctly."""
    # Check that tables were created
    cursor = await db._connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = [row[0] for row in await cursor.fetchall()]

    assert "items" in tables
    assert "images" in tables
    assert "match_metadata" in tables


@pytest.mark.asyncio
async def test_upsert_new_item(db, sample_item):
    """Test inserting a new item."""
    item_id = await db.upsert_item(sample_item)

    assert item_id > 0

    # Verify item was saved
    item = await db.get_item_by_id(item_id)
    assert item is not None
    assert item["title"] == sample_item.title
    assert item["current_price"] == sample_item.current_price
    assert item["source_site"] == sample_item.source_site


@pytest.mark.asyncio
async def test_upsert_updates_existing(db, sample_item):
    """Test updating an existing item."""
    # Insert first time
    item_id1 = await db.upsert_item(sample_item)

    # Update with new price
    sample_item.current_price = 55.00
    item_id2 = await db.upsert_item(sample_item)

    # Should be same item ID
    assert item_id1 == item_id2

    # Verify price updated
    item = await db.get_item_by_id(item_id1)
    assert item["current_price"] == 55.00


@pytest.mark.asyncio
async def test_images_saved(db, sample_item):
    """Test that images are saved with item."""
    item_id = await db.upsert_item(sample_item)

    item = await db.get_item_by_id(item_id)
    assert len(item["image_urls"]) == 2
    assert "12345-1.jpg" in item["image_urls"][0]


@pytest.mark.asyncio
async def test_save_match_metadata(db, sample_item):
    """Test saving match metadata."""
    item_id = await db.upsert_item(sample_item)

    metadata = MatchMetadata(
        item_id=item_id,
        relevance_score=85,
        reasoning="This is an office chair with mesh seat, matches the search query well.",
        confidence="high"
    )

    metadata_id = await db.save_match_metadata(metadata)
    assert metadata_id > 0


@pytest.mark.asyncio
async def test_get_todays_matches(db, sample_item):
    """Test getting today's matches."""
    item_id = await db.upsert_item(sample_item)

    # Add match metadata
    metadata = MatchMetadata(
        item_id=item_id,
        relevance_score=85,
        reasoning="Good match",
        confidence="high"
    )
    await db.save_match_metadata(metadata)

    # Get matches
    matches = await db.get_todays_matches(min_score=70)
    assert len(matches) == 1
    assert matches[0]["title"] == sample_item.title
    assert matches[0]["relevance_score"] == 85


@pytest.mark.asyncio
async def test_get_todays_matches_filters_low_scores(db, sample_item):
    """Test that low-score items are filtered out."""
    item_id = await db.upsert_item(sample_item)

    # Add low score metadata
    metadata = MatchMetadata(
        item_id=item_id,
        relevance_score=50,
        reasoning="Poor match",
        confidence="low"
    )
    await db.save_match_metadata(metadata)

    # Get matches with threshold 70
    matches = await db.get_todays_matches(min_score=70)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_mark_ended_auctions(db, sample_item):
    """Test marking ended auctions as inactive."""
    # Create item with past end date
    sample_item.auction_end = datetime(2020, 1, 1, 12, 0, 0)
    item_id = await db.upsert_item(sample_item)

    # Mark ended
    count = await db.mark_ended_auctions()
    assert count == 1

    # Verify inactive
    item = await db.get_item_by_id(item_id)
    assert item["is_active"] == 0


@pytest.mark.asyncio
async def test_get_stats(db, sample_item):
    """Test getting database statistics."""
    await db.upsert_item(sample_item)

    stats = await db.get_stats()
    assert stats["total_items"] == 1
    assert stats["active_items"] == 1
    assert stats["items_seen_today"] == 1


def test_load_searches_valid_file(tmp_path):
    """Test loading searches from a valid file."""
    config = tmp_path / "searches.json"
    config.write_text("""
    {
        "searches": [
            {
                "id": "search-001",
                "query": "office chair",
                "active": true,
                "created_at": "2025-01-01T00:00:00Z"
            },
            {
                "id": "search-002",
                "query": "standing desk",
                "active": false,
                "created_at": "2025-01-01T00:00:00Z"
            }
        ]
    }
    """)

    searches = load_searches(str(config))

    # Only active searches loaded
    assert len(searches) == 1
    assert searches[0].query == "office chair"


def test_load_searches_missing_file():
    """Test loading from missing file returns empty list."""
    searches = load_searches("/nonexistent/file.json")
    assert searches == []


# ── New tests for get_search_statistics (Bug 3 fix) ─────────────────────────

@pytest.mark.asyncio
async def test_get_search_statistics_counts_todays_items(db, tmp_path):
    """get_search_statistics must count items seen TODAY, not all-time."""
    from datetime import date

    # Write a searches.json with one active search
    config = tmp_path / "searches.json"
    config.write_text("""
    {
        "searches": [
            {
                "id": "search-001",
                "query": "office chair",
                "active": true,
                "created_at": "2025-01-01T00:00:00Z"
            }
        ]
    }
    """)

    # Insert two items for search-001 (seen today by default)
    item1 = AuctionItem(
        search_id="search-001",
        source_site="capital_city",
        external_id="aaa-001",
        title="Ergonomic Office Chair",
        listing_url="https://example.com/lot/aaa-001",
    )
    item2 = AuctionItem(
        search_id="search-001",
        source_site="bidfta",
        external_id="bbb-001",
        title="Mesh Office Chair",
        listing_url="https://example.com/lot/bbb-001",
    )
    await db.upsert_item(item1)
    await db.upsert_item(item2)

    # Force one item to appear as if it was last seen YESTERDAY (old item)
    yesterday = (date.today().replace(day=date.today().day - 1)).isoformat()
    await db._connection.execute(
        "UPDATE items SET last_seen = ? WHERE external_id = ?",
        (yesterday, "aaa-001")
    )
    await db._connection.commit()

    stats = await db.get_search_statistics(min_score=70)

    # Monkeypatch load_searches to use our tmp config
    with patch("src.database.load_searches", return_value=load_searches(str(config))):
        stats = await db.get_search_statistics(min_score=70)

    # Only the item seen TODAY should be counted
    assert stats["office chair"]["total_scraped"] == 1
    assert stats["office chair"]["by_source"].get("bidfta", 0) == 1
    assert stats["office chair"]["by_source"].get("capital_city", 0) == 0


@pytest.mark.asyncio
async def test_get_search_statistics_matched_counts_all_active(db, tmp_path, sample_item):
    """'matched' in stats counts all active items with match_metadata."""
    config = tmp_path / "searches.json"
    config.write_text("""
    {
        "searches": [
            {
                "id": "test-search-001",
                "query": "Test Office Chair with Mesh Seat",
                "active": true,
                "created_at": "2025-01-01T00:00:00Z"
            }
        ]
    }
    """)

    item_id = await db.upsert_item(sample_item)
    await db.save_match_metadata(MatchMetadata(
        item_id=item_id,
        relevance_score=85,
        reasoning="Perfect match",
        confidence="high"
    ))

    with patch("src.database.load_searches", return_value=load_searches(str(config))):
        stats = await db.get_search_statistics(min_score=70)

    query = "Test Office Chair with Mesh Seat"
    assert query in stats
    assert stats[query]["matched"] == 1


# ── New tests for mark_items_as_reported ────────────────────────────────────

@pytest.mark.asyncio
async def test_reported_items_excluded_from_get_matches_for_report(db, tmp_path, sample_item):
    """Items marked as reported do not appear in get_matches_for_report."""
    config = tmp_path / "searches.json"
    config.write_text("""
    {
        "searches": [
            {
                "id": "test-search-001",
                "query": "Test Office Chair with Mesh Seat",
                "active": true,
                "created_at": "2025-01-01T00:00:00Z"
            }
        ]
    }
    """)

    item_id = await db.upsert_item(sample_item)
    await db.save_match_metadata(MatchMetadata(
        item_id=item_id,
        relevance_score=85,
        reasoning="Good match",
        confidence="high"
    ))

    with patch("src.database.load_searches", return_value=load_searches(str(config))):
        # Before reporting: should appear
        matches_before = await db.get_matches_for_report(min_score=70)
        assert len(matches_before) == 1

        # Mark as reported
        await db.mark_items_as_reported([item_id])

        # After reporting: should NOT appear
        matches_after = await db.get_matches_for_report(min_score=70)
        assert len(matches_after) == 0


# ── Tests for the report "Matched" counter consistency (markdown_report bug fix) ─

@pytest.mark.asyncio
async def test_reported_item_not_counted_in_per_search_matched(db, tmp_path, sample_item):
    """After an item is reported, the per-search Matched counter must be 0.

    This is the core bug: the old code used get_search_statistics()'matched')
    which counts all-time matches regardless of reported_at. That caused the report
    to show 'Matched: 3' while simultaneously showing 'No matches found for this
    search' because the links are driven by get_matches_for_report() which filters
    reported items.

    The fix drives the matched counter from the actual display list, so it is always
    consistent with what follows in the report.
    """
    from src.markdown_report import generate_markdown_report
    import tempfile

    config = tmp_path / "searches.json"
    config.write_text("""
    {
        "searches": [
            {
                "id": "test-search-001",
                "query": "Test Office Chair with Mesh Seat",
                "active": true,
                "created_at": "2025-01-01T00:00:00Z"
            }
        ]
    }
    """)

    item_id = await db.upsert_item(sample_item)
    await db.save_match_metadata(MatchMetadata(
        item_id=item_id,
        relevance_score=85,
        reasoning="Good match",
        confidence="high"
    ))

    report_path = str(tmp_path / "test_report.md")

    # First run: item is unreported, should appear with Matched: 1
    with patch("src.database.load_searches", return_value=load_searches(str(config))):
        await generate_markdown_report(db, output_path=report_path, threshold=70)

    first_report = (tmp_path / "test_report.md").read_text()
    assert "✅ **Matched:** 1" in first_report
    assert "*No matches found for this search*" not in first_report

    # Second run: item is now reported, should show Matched: 0, no links
    with patch("src.database.load_searches", return_value=load_searches(str(config))):
        await generate_markdown_report(db, output_path=report_path, threshold=70)

    second_report = (tmp_path / "test_report.md").read_text()
    assert "✅ **Matched:** 0" in second_report
    assert "*No matches found for this search*" in second_report
