"""Tests for the database module."""

import asyncio
import os
import tempfile
from datetime import date, datetime

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
