"""SQLite database operations for auction monitoring."""

import asyncio
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class Search:
    """Represents a search query."""
    id: str
    query: str
    active: bool
    created_at: datetime


@dataclass
class AuctionItem:
    """Represents an auction item."""
    id: Optional[int] = None
    search_id: str = ""
    source_site: str = ""
    external_id: str = ""
    title: str = ""
    description: str = ""
    current_price: Optional[float] = None
    msrp: Optional[float] = None
    discount_pct: Optional[float] = None
    condition: str = ""
    auction_end: Optional[datetime] = None
    pickup_location: str = ""
    pickup_dates: str = ""
    listing_url: str = ""
    first_seen: Optional[date] = None
    last_seen: Optional[date] = None
    is_active: bool = True
    image_urls: list[str] = field(default_factory=list)


@dataclass
class MatchMetadata:
    """Represents semantic matching metadata for an item."""
    id: Optional[int] = None
    item_id: int = 0
    relevance_score: int = 0
    reasoning: str = ""
    confidence: str = ""
    matched_at: Optional[datetime] = None


class Database:
    """Async SQLite database manager for auction data."""

    def __init__(self, db_path: str = "auction_data.db"):
        self.db_path = Path(db_path)
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Connect to the database and initialize schema."""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._init_schema()
        logger.info(f"Connected to database: {self.db_path}")

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _init_schema(self) -> None:
        """Initialize database schema."""
        await self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_id TEXT NOT NULL,
                source_site TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                current_price REAL,
                msrp REAL,
                discount_pct REAL,
                condition TEXT,
                auction_end TIMESTAMP,
                pickup_location TEXT,
                pickup_dates TEXT,
                listing_url TEXT NOT NULL,
                first_seen DATE NOT NULL,
                last_seen DATE NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                reported_at TIMESTAMP,
                UNIQUE(source_site, external_id, search_id)
            );

            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS match_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                relevance_score INTEGER NOT NULL,
                reasoning TEXT,
                confidence TEXT,
                matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_items_search ON items(search_id);
            CREATE INDEX IF NOT EXISTS idx_items_last_seen ON items(last_seen);
            CREATE INDEX IF NOT EXISTS idx_items_active ON items(is_active);
            CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_site, external_id);
        """)
        await self._connection.commit()

    async def upsert_item(self, item: AuctionItem) -> int:
        """Insert or update an auction item. Returns the item ID."""
        today = date.today()

        # Check if item already exists
        cursor = await self._connection.execute(
            """SELECT id, first_seen FROM items
               WHERE source_site = ? AND external_id = ? AND search_id = ?""",
            (item.source_site, item.external_id, item.search_id)
        )
        existing = await cursor.fetchone()

        if existing:
            # Update existing item
            item_id = existing["id"]
            first_seen = existing["first_seen"]
            await self._connection.execute("""
                UPDATE items SET
                    title = ?,
                    description = ?,
                    current_price = ?,
                    msrp = ?,
                    discount_pct = ?,
                    condition = ?,
                    auction_end = ?,
                    pickup_location = ?,
                    pickup_dates = ?,
                    listing_url = ?,
                    last_seen = ?,
                    is_active = 1
                WHERE id = ?
            """, (
                item.title,
                item.description,
                item.current_price,
                item.msrp,
                item.discount_pct,
                item.condition,
                item.auction_end.isoformat() if item.auction_end else None,
                item.pickup_location,
                item.pickup_dates,
                item.listing_url,
                today.isoformat(),
                item_id
            ))
            logger.debug(f"Updated item {item_id}: {item.title[:50]}")
        else:
            # Insert new item
            cursor = await self._connection.execute("""
                INSERT INTO items (
                    search_id, source_site, external_id, title, description,
                    current_price, msrp, discount_pct, condition, auction_end,
                    pickup_location, pickup_dates, listing_url, first_seen, last_seen, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                item.search_id,
                item.source_site,
                item.external_id,
                item.title,
                item.description,
                item.current_price,
                item.msrp,
                item.discount_pct,
                item.condition,
                item.auction_end.isoformat() if item.auction_end else None,
                item.pickup_location,
                item.pickup_dates,
                item.listing_url,
                today.isoformat(),
                today.isoformat()
            ))
            item_id = cursor.lastrowid
            logger.debug(f"Inserted new item {item_id}: {item.title[:50]}")

        # Update images
        await self._connection.execute("DELETE FROM images WHERE item_id = ?", (item_id,))
        for url in item.image_urls:
            await self._connection.execute(
                "INSERT INTO images (item_id, url) VALUES (?, ?)",
                (item_id, url)
            )

        await self._connection.commit()
        return item_id

    async def save_match_metadata(self, metadata: MatchMetadata) -> int:
        """Save semantic matching metadata for an item."""
        cursor = await self._connection.execute("""
            INSERT INTO match_metadata (item_id, relevance_score, reasoning, confidence)
            VALUES (?, ?, ?, ?)
        """, (
            metadata.item_id,
            metadata.relevance_score,
            metadata.reasoning,
            metadata.confidence
        ))
        await self._connection.commit()
        return cursor.lastrowid

    async def get_todays_matches(self, min_score: int = 70) -> list[dict]:
        """Get all items matched today with score >= threshold."""
        today = date.today().isoformat()
        cursor = await self._connection.execute("""
            SELECT
                i.*,
                m.relevance_score,
                m.reasoning,
                m.confidence,
                i.first_seen = i.last_seen as is_new
            FROM items i
            JOIN match_metadata m ON i.id = m.item_id
            WHERE i.last_seen = ?
              AND i.is_active = 1
              AND m.relevance_score >= ?
            ORDER BY m.relevance_score DESC
        """, (today, min_score))

        rows = await cursor.fetchall()
        results = []
        for row in rows:
            item_dict = dict(row)
            # Get images
            img_cursor = await self._connection.execute(
                "SELECT url FROM images WHERE item_id = ?", (row["id"],)
            )
            images = await img_cursor.fetchall()
            item_dict["image_urls"] = [img["url"] for img in images]
            results.append(item_dict)

        return results

    async def get_matches_for_report(self, min_score: int = 70) -> list[dict]:
        """Get all active items with matches for report (only unreported items)."""
        # Get all searches to build a lookup
        searches = load_searches()
        search_lookup = {s.id: s.query for s in searches}

        cursor = await self._connection.execute("""
            SELECT
                i.*,
                m.relevance_score,
                m.reasoning,
                m.confidence,
                i.first_seen = i.last_seen as is_new
            FROM items i
            JOIN match_metadata m ON i.id = m.item_id
            WHERE i.is_active = 1
              AND m.relevance_score >= ?
              AND i.reported_at IS NULL
            ORDER BY i.last_seen DESC, m.relevance_score DESC
        """, (min_score,))

        rows = await cursor.fetchall()
        results = []
        for row in rows:
            item_dict = dict(row)
            # Get images
            img_cursor = await self._connection.execute(
                "SELECT url FROM images WHERE item_id = ?", (row["id"],)
            )
            images = await img_cursor.fetchall()
            item_dict["image_urls"] = [img["url"] for img in images]

            # Add search query
            item_dict["search_query"] = search_lookup.get(row["search_id"], "Unknown")

            results.append(item_dict)

        return results

    async def mark_ended_auctions(self) -> int:
        """Mark auctions that have ended as inactive. Returns count of updated items."""
        now = datetime.utcnow().isoformat()
        cursor = await self._connection.execute("""
            UPDATE items SET is_active = 0
            WHERE auction_end < ? AND is_active = 1
        """, (now,))
        await self._connection.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info(f"Marked {count} ended auctions as inactive")
        return count

    async def get_item_by_id(self, item_id: int) -> Optional[dict]:
        """Get a single item by ID."""
        cursor = await self._connection.execute(
            "SELECT * FROM items WHERE id = ?", (item_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None

        item_dict = dict(row)
        img_cursor = await self._connection.execute(
            "SELECT url FROM images WHERE item_id = ?", (item_id,)
        )
        images = await img_cursor.fetchall()
        item_dict["image_urls"] = [img["url"] for img in images]
        return item_dict

    async def get_items_needing_msrp(self) -> list[dict]:
        """Get items that have no MSRP for price lookup."""
        today = date.today().isoformat()
        cursor = await self._connection.execute("""
            SELECT * FROM items
            WHERE last_seen = ? AND is_active = 1 AND msrp IS NULL
        """, (today,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_item_msrp(self, item_id: int, msrp: float, discount_pct: float) -> None:
        """Update MSRP and discount percentage for an item."""
        await self._connection.execute("""
            UPDATE items SET msrp = ?, discount_pct = ? WHERE id = ?
        """, (msrp, discount_pct, item_id))
        await self._connection.commit()

    async def get_stats(self) -> dict:
        """Get database statistics."""
        cursor = await self._connection.execute(
            "SELECT COUNT(*) as total FROM items"
        )
        total = (await cursor.fetchone())["total"]

        cursor = await self._connection.execute(
            "SELECT COUNT(*) as active FROM items WHERE is_active = 1"
        )
        active = (await cursor.fetchone())["active"]

        today = date.today().isoformat()
        cursor = await self._connection.execute(
            "SELECT COUNT(*) as today FROM items WHERE last_seen = ?"
        , (today,))
        seen_today = (await cursor.fetchone())["today"]

        return {
            "total_items": total,
            "active_items": active,
            "items_seen_today": seen_today
        }

    async def get_search_statistics(self, min_score: int = 70) -> dict:
        """Get statistics for each search query."""
        searches = load_searches()
        stats = {}

        for search in searches:
            # Count total items scraped for this search
            cursor = await self._connection.execute("""
                SELECT COUNT(*) as total FROM items
                WHERE search_id = ? AND is_active = 1
            """, (search.id,))
            total = (await cursor.fetchone())["total"]

            # Count items that passed semantic matching
            cursor = await self._connection.execute("""
                SELECT COUNT(*) as matched FROM items i
                JOIN match_metadata m ON i.id = m.item_id
                WHERE i.search_id = ?
                  AND i.is_active = 1
                  AND m.relevance_score >= ?
            """, (search.id, min_score))
            matched = (await cursor.fetchone())["matched"]

            stats[search.query] = {
                "total_scraped": total,
                "matched": matched,
                "search_id": search.id
            }

        return stats

    async def mark_items_as_reported(self, item_ids: list[int]) -> int:
        """Mark items as reported so they don't appear in future reports."""
        if not item_ids:
            return 0

        now = datetime.utcnow().isoformat()
        placeholders = ','.join(['?'] * len(item_ids))
        cursor = await self._connection.execute(f"""
            UPDATE items SET reported_at = ?
            WHERE id IN ({placeholders})
        """, [now] + item_ids)
        await self._connection.commit()
        count = cursor.rowcount
        if count > 0:
            logger.info(f"Marked {count} items as reported")
        return count


def load_searches(config_path: str = "searches.json") -> list[Search]:
    """Load active searches from configuration file."""
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"Search config not found: {config_path}")
        return []

    with open(path) as f:
        data = json.load(f)

    searches = []
    for s in data.get("searches", []):
        if s.get("active", True):
            searches.append(Search(
                id=s["id"],
                query=s["query"],
                active=s.get("active", True),
                created_at=datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
            ))

    logger.info(f"Loaded {len(searches)} active searches")
    return searches
