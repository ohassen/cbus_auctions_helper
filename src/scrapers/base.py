"""Base scraper class with common functionality."""

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, AsyncIterator
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout

from ..database import AuctionItem
from .config import (
    get_selectors,
    get_patterns,
    SOLD_INDICATORS,
    IMAGE_ATTRIBUTES,
    DEFAULT_MAX_IMAGES,
)

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

    def _extract_id_from_url(self, url: str) -> str:
        """Extract item ID from URL using configured patterns."""
        patterns = get_patterns("id", self.name)
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        return str(hash(url))

    async def _is_item_sold_or_closed(self) -> bool:
        """Check if the item is sold, closed, or no longer available."""
        page_text = await self._page.inner_text("body")
        page_text_lower = page_text.lower()

        # Check if any sold indicator appears in the page
        if any(indicator in page_text_lower for indicator in SOLD_INDICATORS):
            # Look for these terms in prominent locations (status, badges, etc.)
            status_selectors = get_selectors("status", self.name)

            for selector in status_selectors:
                status_text = await self._safe_get_text(selector)
                if status_text:
                    status_lower = status_text.lower()
                    if any(indicator in status_lower for indicator in SOLD_INDICATORS):
                        logger.info(f"{self.name}: Item is sold/closed (status: {status_text})")
                        return True

        return False

    async def _get_title(self) -> str:
        """Extract item title using configured selectors."""
        selectors = get_selectors("title", self.name)
        for selector in selectors:
            title = await self._safe_get_text(selector)
            if title and len(title) > 3 and len(title) < 500:
                title = title.strip()
                # Skip generic navigation text
                from .config import NAVIGATION_TERMS
                if title.lower() not in NAVIGATION_TERMS:
                    logger.debug(f"{self.name}: Found title via selector '{selector}': {title[:50]}")
                    return title

        # Fallback: try page title
        page_title = await self._page.title()
        if page_title:
            # Remove site name from title
            title = page_title.split("|")[0].split("-")[0].strip()
            if len(title) > 3:
                site_names = ["capital city online auction", "auction", "bidfta"]
                if not any(site_name in title.lower() for site_name in site_names):
                    return title

        logger.debug(f"{self.name}: Could not find title")
        return ""

    async def _get_description(self) -> str:
        """Extract item description using configured selectors."""
        selectors = get_selectors("description", self.name)
        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text and len(text) > 20:
                return text[:2000]  # Limit length
        return ""

    async def _get_current_price(self) -> Optional[float]:
        """Extract current bid price using configured selectors and patterns."""
        selectors = get_selectors("current_price", self.name)

        for selector in selectors:
            text = await self._safe_get_text(selector)
            price = self._parse_price(text)
            if price is not None and price > 0:
                return price

        # Look for price patterns in page text
        page_text = await self._page.inner_text("body")
        patterns = get_patterns("current_price", self.name)
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                price = self._parse_price(match.group(1))
                if price and price > 0:
                    return price

        return None

    async def _get_msrp(self) -> Optional[float]:
        """Extract MSRP/retail price using configured selectors and patterns."""
        selectors = get_selectors("msrp", self.name)

        for selector in selectors:
            text = await self._safe_get_text(selector)
            price = self._parse_price(text)
            if price is not None:
                return price

        page_text = await self._page.inner_text("body")
        patterns = get_patterns("msrp", self.name)
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return self._parse_price(match.group(1))

        return None

    async def _get_condition(self) -> str:
        """Extract item condition using configured selectors and patterns."""
        selectors = get_selectors("condition", self.name)
        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text:
                return text

        page_text = await self._page.inner_text("body")
        patterns = get_patterns("condition", self.name)
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:100]

        return ""

    async def _get_auction_end(self) -> Optional[str]:
        """Extract auction end datetime using configured selectors and patterns."""
        selectors = get_selectors("auction_end", self.name)
        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text:
                dt = self._parse_datetime(text)
                if dt:
                    logger.debug(f"{self.name}: Found auction end via selector '{selector}': {dt}")
                    return dt

        # Look for text patterns in the page
        page_text = await self._page.inner_text("body")
        patterns = get_patterns("auction_end", self.name)
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                dt = self._parse_datetime(match.group(1))
                if dt:
                    logger.debug(f"{self.name}: Found auction end via pattern: {dt}")
                    return dt

        logger.debug(f"{self.name}: Could not find auction end time")
        return None

    async def _get_pickup_info(self) -> tuple[str, str]:
        """Extract pickup location and dates using configured patterns."""
        location = ""
        dates = ""

        page_text = await self._page.inner_text("body")

        # Extract location
        loc_patterns = get_patterns("pickup_location", self.name)
        for pattern in loc_patterns:
            loc_match = re.search(pattern, page_text, re.IGNORECASE)
            if loc_match:
                location = loc_match.group(1).strip()
                break

        # Extract dates
        date_patterns = get_patterns("pickup_dates", self.name)
        for pattern in date_patterns:
            date_match = re.search(pattern, page_text, re.IGNORECASE)
            if date_match:
                dates = date_match.group(1).strip()
                break

        return location, dates

    async def _get_images(self) -> list[str]:
        """Extract all image URLs for the item using configured selectors."""
        image_urls = []

        selectors = get_selectors("images", self.name)

        for selector in selectors:
            for attr in IMAGE_ATTRIBUTES:
                urls = await self._get_all_attributes(selector, attr)
                for url in urls:
                    if url and not url.startswith("data:") and "placeholder" not in url.lower():
                        full_url = urljoin(self.base_url, url)
                        if full_url not in image_urls:
                            image_urls.append(full_url)

        return image_urls[:DEFAULT_MAX_IMAGES]

    @abstractmethod
    async def search(self, query: str) -> AsyncIterator[str]:
        """Search for items and yield listing URLs."""
        pass

    @abstractmethod
    async def scrape_listing(self, url: str, search_id: str) -> Optional[AuctionItem]:
        """Scrape a single listing page."""
        pass

    async def scrape_all(self, query: str, search_id: str, max_items: Optional[int] = None) -> list[AuctionItem]:
        """Scrape all listings for a search query.

        Args:
            query: Search query string
            search_id: Database ID for this search
            max_items: Maximum number of items to scrape (None = unlimited)
        """
        items = []
        try:
            async for listing_url in self.search(query):
                # Check if we've reached the limit
                if max_items is not None and len(items) >= max_items:
                    logger.info(f"Reached max_items limit ({max_items}) for '{query}'")
                    break

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
