"""Scraper for BidFTA.com (Columbus locations only)."""

import asyncio
import logging
import re
from typing import Optional, AsyncIterator
from urllib.parse import urljoin, urlencode, quote_plus

from playwright.async_api import TimeoutError as PlaywrightTimeout

from .base import BaseScraper, ScraperConfig
from ..database import AuctionItem

logger = logging.getLogger(__name__)

# Columbus-area location identifiers
COLUMBUS_LOCATIONS = [
    "columbus",
    "westerville",
    "grove city",
    "dublin",
    "gahanna",
    "reynoldsburg",
    "hilliard",
    "worthington",
    "upper arlington",
    "pickerington",
    "canal winchester",
    "groveport",
    "whitehall",
    "bexley",
    "grandview",
    "powell",
    "delaware",
    "newark",
    "lancaster",
    "circleville",
    "marysville",
    "mount vernon",
    "43",  # Columbus ZIP codes start with 43
]


class BidFTAScraper(BaseScraper):
    """Scraper for BidFTA.com, filtering for Columbus-area locations."""

    name = "bidfta"
    base_url = "https://www.bidfta.com"

    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config)

    def _is_columbus_location(self, location_text: str) -> bool:
        """Check if a location is in the Columbus area."""
        if not location_text:
            return False
        location_lower = location_text.lower()
        return any(loc in location_lower for loc in COLUMBUS_LOCATIONS)

    async def search(self, query: str) -> AsyncIterator[str]:
        """Search for items and yield listing URLs (Columbus locations only)."""
        # BidFTA search URL pattern
        search_url = f"{self.base_url}/search?{urlencode({'q': query})}"

        page_num = 1
        max_pages = 10  # Safety limit

        while page_num <= max_pages:
            try:
                current_url = search_url if page_num == 1 else f"{search_url}&page={page_num}"
                logger.info(f"Searching page {page_num}: {current_url}")

                await self._page.goto(current_url, wait_until="networkidle")
                await asyncio.sleep(1.5)  # Allow JS to render

                # BidFTA uses React/dynamic content, wait for listings
                try:
                    await self._page.wait_for_selector(
                        ".auction-item, .lot-item, .product-card, [class*='item-card'], [class*='auction']",
                        timeout=10000
                    )
                except PlaywrightTimeout:
                    logger.info("No items found on page")
                    break

                # Find all listing items with location info
                items_found = 0
                columbus_items = 0

                # Try multiple selector strategies
                item_selectors = [
                    ".auction-item",
                    ".lot-item",
                    ".product-card",
                    "[class*='item-card']",
                    "[class*='lot-card']",
                    ".search-result-item",
                    "[data-lot-id]",
                ]

                for selector in item_selectors:
                    items = await self._page.query_selector_all(selector)
                    if items:
                        logger.info(f"Found {len(items)} items with selector: {selector}")
                        items_found = len(items)

                        for item in items:
                            # Get location text
                            location_text = ""
                            location_selectors = [
                                ".location",
                                ".pickup-location",
                                "[class*='location']",
                                ".facility",
                                ".warehouse",
                            ]
                            for loc_sel in location_selectors:
                                loc_el = await item.query_selector(loc_sel)
                                if loc_el:
                                    location_text = await loc_el.inner_text()
                                    break

                            # If no specific location element, search in item text
                            if not location_text:
                                item_text = await item.inner_text()
                                # Look for location patterns
                                location_match = re.search(
                                    r"(?:Location|Pickup|Facility)[:\s]*([^\n]+)",
                                    item_text,
                                    re.IGNORECASE
                                )
                                if location_match:
                                    location_text = location_match.group(1)

                            # Check if Columbus area
                            if self._is_columbus_location(location_text):
                                # Get item URL
                                link = await item.query_selector("a[href*='lot'], a[href*='item'], a[href*='details']")
                                if not link:
                                    link = await item.query_selector("a")
                                if link:
                                    href = await link.get_attribute("href")
                                    if href:
                                        full_url = urljoin(self.base_url, href)
                                        columbus_items += 1
                                        yield full_url
                        break  # Found items with this selector

                logger.info(f"Page {page_num}: {items_found} total items, {columbus_items} in Columbus area")

                if items_found == 0:
                    break

                # Check for next page
                next_button = await self._page.query_selector(
                    "a:has-text('Next'), button:has-text('Next'), .pagination-next, [class*='next-page'], a[rel='next']"
                )
                if not next_button:
                    logger.info("No more pages")
                    break

                # Check if next button is disabled
                is_disabled = await next_button.get_attribute("disabled")
                aria_disabled = await next_button.get_attribute("aria-disabled")
                classes = await next_button.get_attribute("class") or ""
                if is_disabled or aria_disabled == "true" or "disabled" in classes:
                    break

                page_num += 1
                await self._rate_limit()

            except PlaywrightTimeout:
                logger.warning(f"Timeout on search page {page_num}")
                break
            except Exception as e:
                logger.error(f"Error on search page {page_num}: {e}")
                break

    async def scrape_listing(self, url: str, search_id: str) -> Optional[AuctionItem]:
        """Scrape a single listing page."""
        try:
            await self._page.goto(url, wait_until="networkidle")
            await asyncio.sleep(1)  # Allow JS to render

            # Extract external ID from URL
            external_id = self._extract_id_from_url(url)

            # Title
            title = await self._get_title()
            if not title:
                logger.warning(f"Could not find title for {url}")
                return None

            # Description
            description = await self._get_description()

            # Current price
            current_price = await self._get_current_price()

            # MSRP/Retail price
            msrp = await self._get_msrp()

            # Calculate discount
            discount_pct = None
            if msrp and current_price and msrp > 0:
                discount_pct = round((msrp - current_price) / msrp * 100, 1)

            # Condition
            condition = await self._get_condition()

            # Auction end time
            auction_end = await self._get_auction_end()

            # Pickup info
            pickup_location, pickup_dates = await self._get_pickup_info()

            # Verify this is a Columbus location
            if not self._is_columbus_location(pickup_location):
                logger.info(f"Skipping non-Columbus item: {pickup_location}")
                return None

            # Images
            image_urls = await self._get_images()

            return AuctionItem(
                search_id=search_id,
                source_site=self.name,
                external_id=external_id,
                title=title,
                description=description,
                current_price=current_price,
                msrp=msrp,
                discount_pct=discount_pct,
                condition=condition,
                auction_end=auction_end,
                pickup_location=pickup_location,
                pickup_dates=pickup_dates,
                listing_url=url,
                image_urls=image_urls
            )

        except Exception as e:
            logger.error(f"Error scraping listing {url}: {e}")
            return None

    def _extract_id_from_url(self, url: str) -> str:
        """Extract item ID from URL."""
        patterns = [
            r"lot[_/-]?(\d+)",
            r"item[_/-]?(\d+)",
            r"/(\d+)/?$",
            r"id=(\d+)",
            r"lotId=(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        return str(hash(url))

    async def _get_title(self) -> str:
        """Extract item title."""
        selectors = [
            "h1.lot-title",
            "h1.item-title",
            "h1.product-title",
            "h1[class*='title']",
            ".lot-details h1",
            ".item-details h1",
            "h1",
        ]
        for selector in selectors:
            title = await self._safe_get_text(selector)
            if title and len(title) > 3:
                return title
        return ""

    async def _get_description(self) -> str:
        """Extract item description."""
        selectors = [
            ".lot-description",
            ".item-description",
            ".product-description",
            "[class*='description']",
            ".details-content",
            "#description",
        ]
        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text and len(text) > 20:
                return text
        return ""

    async def _get_current_price(self) -> Optional[float]:
        """Extract current bid price."""
        selectors = [
            ".current-bid",
            ".high-bid",
            ".current-price",
            ".bid-amount",
            "[class*='current'][class*='bid']",
            "[class*='price']",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            price = self._parse_price(text)
            if price is not None:
                return price

        # Look for price patterns in page
        page_text = await self._page.inner_text("body")
        patterns = [
            r"Current\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"High\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"Your\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return self._parse_price(match.group(1))

        return None

    async def _get_msrp(self) -> Optional[float]:
        """Extract MSRP/retail price if available."""
        selectors = [
            ".msrp",
            ".retail-price",
            ".original-price",
            ".list-price",
            "[class*='msrp']",
            "[class*='retail']",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            price = self._parse_price(text)
            if price is not None:
                return price

        # Look in page text
        page_text = await self._page.inner_text("body")
        patterns = [
            r"MSRP[:\s]*\$?([\d,]+\.?\d*)",
            r"Retail(?:\s*Value)?[:\s]*\$?([\d,]+\.?\d*)",
            r"Original\s*Price[:\s]*\$?([\d,]+\.?\d*)",
            r"List\s*Price[:\s]*\$?([\d,]+\.?\d*)",
            r"Value[:\s]*\$?([\d,]+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return self._parse_price(match.group(1))

        return None

    async def _get_condition(self) -> str:
        """Extract item condition."""
        selectors = [
            ".condition",
            ".item-condition",
            "[class*='condition']",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text:
                return text

        # Search in page text
        page_text = await self._page.inner_text("body")
        match = re.search(r"Condition[:\s]*([^\n]+)", page_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return ""

    async def _get_auction_end(self) -> Optional[str]:
        """Extract auction end datetime."""
        selectors = [
            ".end-time",
            ".auction-end",
            ".closing-time",
            ".countdown",
            "[class*='end']",
            "[class*='closing']",
            "[class*='countdown']",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            dt = self._parse_datetime(text)
            if dt:
                return dt

        # Look for end time patterns in page
        page_text = await self._page.inner_text("body")
        patterns = [
            r"Ends?[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Closing[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Auction\s*End[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Closes[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return self._parse_datetime(match.group(1))

        return None

    async def _get_pickup_info(self) -> tuple[str, str]:
        """Extract pickup location and dates."""
        location = ""
        dates = ""

        # Try specific pickup selectors
        pickup_selectors = [
            ".pickup-info",
            ".pickup-location",
            ".facility-info",
            ".warehouse-info",
            "[class*='pickup']",
            "[class*='facility']",
        ]

        for selector in pickup_selectors:
            el = await self._page.query_selector(selector)
            if el:
                text = await el.inner_text()
                if text:
                    # Parse location and dates
                    lines = text.split("\n")
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        # Check if this is an address line
                        if any(word in line.lower() for word in ["street", "ave", "road", "blvd", "drive", "lane", "way", "circle"]) or re.search(r"\d{5}", line):
                            location = line if not location else f"{location}, {line}"
                        # Check if this is a date/time line
                        elif any(word in line.lower() for word in ["am", "pm", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]) or re.search(r"\d{1,2}/\d{1,2}", line):
                            dates = line if not dates else f"{dates}; {line}"
                    break

        # Fallback: search in page text
        if not location:
            page_text = await self._page.inner_text("body")
            # Look for facility/warehouse name
            match = re.search(r"(?:Facility|Warehouse|Location)[:\s]*([^\n]+)", page_text, re.IGNORECASE)
            if match:
                location = match.group(1).strip()

        if not dates:
            page_text = await self._page.inner_text("body")
            match = re.search(r"Pickup\s*(?:Date|Time|Hour)s?[:\s]*([^\n]+)", page_text, re.IGNORECASE)
            if match:
                dates = match.group(1).strip()

        return location, dates

    async def _get_images(self) -> list[str]:
        """Extract all image URLs for the item."""
        image_urls = []

        # Common image selectors for BidFTA
        selectors = [
            ".lot-images img",
            ".item-images img",
            ".product-gallery img",
            ".image-gallery img",
            ".carousel img",
            "[class*='gallery'] img",
            "[class*='image-container'] img",
            ".slick-slide img",
            ".swiper-slide img",
        ]

        for selector in selectors:
            urls = await self._get_all_attributes(selector, "src")
            for url in urls:
                if url and not url.startswith("data:") and "placeholder" not in url.lower():
                    full_url = urljoin(self.base_url, url)
                    if full_url not in image_urls:
                        image_urls.append(full_url)

            # Check data-src for lazy loading
            urls = await self._get_all_attributes(selector, "data-src")
            for url in urls:
                if url and not url.startswith("data:"):
                    full_url = urljoin(self.base_url, url)
                    if full_url not in image_urls:
                        image_urls.append(full_url)

        # Also try data-lazy for some carousel libraries
        if not image_urls:
            urls = await self._get_all_attributes("img[data-lazy]", "data-lazy")
            for url in urls:
                if url:
                    full_url = urljoin(self.base_url, url)
                    image_urls.append(full_url)

        return image_urls[:10]  # Limit to 10 images
