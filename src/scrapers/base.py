"""Base scraper class with common functionality."""

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, AsyncIterator

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from ..database import AuctionItem

logger = logging.getLogger(__name__)


@dataclass
class ScraperConfig:
    """Configuration for a scraper."""
    rate_limit_delay: float = 0.5  # seconds between requests
    max_retries: int = 3
    timeout: int = 30000  # milliseconds
    headless: bool = True


class BaseScraper(ABC):
    """Base class for auction site scrapers."""

    name: str = "base"
    base_url: str = ""

    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._playwright = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self) -> None:
        """Start the browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.config.timeout)
        logger.info(f"Started {self.name} scraper")

    async def stop(self) -> None:
        """Stop the browser."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info(f"Stopped {self.name} scraper")

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        await asyncio.sleep(self.config.rate_limit_delay)

    async def _safe_get_text(self, selector: str, default: str = "") -> str:
        """Safely get text from an element."""
        try:
            element = await self._page.query_selector(selector)
            if element:
                return (await element.inner_text()).strip()
        except Exception as e:
            logger.debug(f"Failed to get text for {selector}: {e}")
        return default

    async def _safe_get_attribute(self, selector: str, attr: str, default: str = "") -> str:
        """Safely get attribute from an element."""
        try:
            element = await self._page.query_selector(selector)
            if element:
                value = await element.get_attribute(attr)
                return value.strip() if value else default
        except Exception as e:
            logger.debug(f"Failed to get attribute {attr} for {selector}: {e}")
        return default

    async def _get_all_texts(self, selector: str) -> list[str]:
        """Get text from all matching elements."""
        texts = []
        try:
            elements = await self._page.query_selector_all(selector)
            for el in elements:
                text = await el.inner_text()
                if text:
                    texts.append(text.strip())
        except Exception as e:
            logger.debug(f"Failed to get texts for {selector}: {e}")
        return texts

    async def _get_all_attributes(self, selector: str, attr: str) -> list[str]:
        """Get attribute values from all matching elements."""
        values = []
        try:
            elements = await self._page.query_selector_all(selector)
            for el in elements:
                value = await el.get_attribute(attr)
                if value:
                    values.append(value.strip())
        except Exception as e:
            logger.debug(f"Failed to get attributes for {selector}: {e}")
        return values

    def _parse_price(self, price_str: str) -> Optional[float]:
        """Parse a price string to float."""
        if not price_str:
            return None
        try:
            # Remove currency symbols and commas
            cleaned = re.sub(r"[^\d.]", "", price_str)
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse common datetime formats."""
        if not dt_str:
            return None

        formats = [
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %I:%M:%S %p",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%B %d, %Y %I:%M %p",
            "%b %d, %Y %I:%M %p",
            "%m-%d-%Y %I:%M %p",
        ]

        # Clean up the string
        dt_str = dt_str.strip().replace("\n", " ").replace("  ", " ")

        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue

        logger.debug(f"Could not parse datetime: {dt_str}")
        return None

    @abstractmethod
    async def search(self, query: str) -> AsyncIterator[str]:
        """Search for items and yield listing URLs."""
        pass

    @abstractmethod
    async def scrape_listing(self, url: str, search_id: str) -> Optional[AuctionItem]:
        """Scrape a single listing page."""
        pass

    async def scrape_all(self, query: str, search_id: str) -> list[AuctionItem]:
        """Scrape all listings for a search query."""
        items = []
        try:
            async for listing_url in self.search(query):
                await self._rate_limit()
                try:
                    item = await self.scrape_listing(listing_url, search_id)
                    if item:
                        items.append(item)
                        logger.info(f"Scraped: {item.title[:50]}...")
                except Exception as e:
                    logger.error(f"Error scraping {listing_url}: {e}")
                    continue
        except Exception as e:
            logger.error(f"Error during search for '{query}': {e}")

        logger.info(f"Scraped {len(items)} items for query '{query}' from {self.name}")
        return items
