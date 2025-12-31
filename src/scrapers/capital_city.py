"""Scraper for Capital City Online Auction (capitalcityonlineauction.com)."""

import asyncio
import logging
import re
from typing import Optional, AsyncIterator
from urllib.parse import urljoin, urlencode

from playwright.async_api import TimeoutError as PlaywrightTimeout

from .base import BaseScraper, ScraperConfig
from ..database import AuctionItem

logger = logging.getLogger(__name__)


class CapitalCityScraper(BaseScraper):
    """Scraper for Capital City Online Auction."""

    name = "capital_city"
    base_url = "https://capitalcityonlineauction.com"

    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config)

    async def search(self, query: str) -> AsyncIterator[str]:
        """Search for items and yield listing URLs."""
        # Capital City uses a search page with pagination
        search_url = f"{self.base_url}/cgi-bin/mnlist.cgi?{urlencode({'search': query})}"

        page_num = 1
        max_pages = 10  # Safety limit

        while page_num <= max_pages:
            try:
                current_url = search_url if page_num == 1 else f"{search_url}&page={page_num}"
                logger.info(f"Searching page {page_num}: {current_url}")

                await self._page.goto(current_url, wait_until="networkidle")
                await asyncio.sleep(1)  # Allow JS to render

                # Look for listing links - common patterns for auction sites
                # Try multiple selector strategies
                listing_links = []

                # Strategy 1: Links in table rows
                links = await self._page.query_selector_all("table tr td a[href*='mndetails']")
                for link in links:
                    href = await link.get_attribute("href")
                    if href:
                        listing_links.append(urljoin(self.base_url, href))

                # Strategy 2: Links with lot/item in URL
                if not listing_links:
                    links = await self._page.query_selector_all("a[href*='lot'], a[href*='item'], a[href*='details']")
                    for link in links:
                        href = await link.get_attribute("href")
                        if href and ("lot" in href.lower() or "item" in href.lower() or "details" in href.lower()):
                            listing_links.append(urljoin(self.base_url, href))

                # Strategy 3: Product cards/tiles
                if not listing_links:
                    cards = await self._page.query_selector_all(".product-card a, .auction-item a, .lot-card a, .item-card a")
                    for card in cards:
                        href = await card.get_attribute("href")
                        if href:
                            listing_links.append(urljoin(self.base_url, href))

                # Deduplicate
                listing_links = list(dict.fromkeys(listing_links))

                if not listing_links:
                    logger.info(f"No listings found on page {page_num}")
                    break

                logger.info(f"Found {len(listing_links)} listings on page {page_num}")
                for url in listing_links:
                    yield url

                # Check for next page
                next_button = await self._page.query_selector(
                    "a:has-text('Next'), a:has-text('›'), a.next-page, .pagination a:has-text('Next')"
                )
                if not next_button:
                    logger.info("No more pages")
                    break

                # Check if next button is disabled
                is_disabled = await next_button.get_attribute("disabled")
                classes = await next_button.get_attribute("class") or ""
                if is_disabled or "disabled" in classes:
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
            await asyncio.sleep(0.5)  # Allow JS to render

            # Extract external ID from URL
            external_id = self._extract_id_from_url(url)

            # Title - try multiple selectors
            title = await self._safe_get_text("h1, .item-title, .lot-title, .product-title")
            if not title:
                title = await self._safe_get_text("title")
                title = title.split("|")[0].strip() if title else ""

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
        # Try common patterns
        patterns = [
            r"id=(\d+)",
            r"lot[_-]?(\d+)",
            r"item[_-]?(\d+)",
            r"/(\d+)/?$",
            r"details[/_](\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        # Fallback: use URL hash
        return str(hash(url))

    async def _get_description(self) -> str:
        """Extract item description."""
        selectors = [
            ".item-description",
            ".lot-description",
            ".product-description",
            "#description",
            "[class*='description']",
            ".details-text",
        ]
        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text and len(text) > 20:
                return text

        # Try getting text from a description table
        rows = await self._page.query_selector_all("table tr")
        for row in rows:
            text = await row.inner_text()
            if "description" in text.lower():
                return text.replace("Description", "").replace("description", "").strip()

        return ""

    async def _get_current_price(self) -> Optional[float]:
        """Extract current bid price."""
        selectors = [
            ".current-bid",
            ".current-price",
            ".high-bid",
            ".winning-bid",
            "[class*='bid'] [class*='price']",
            "[class*='current']",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            price = self._parse_price(text)
            if price is not None:
                return price

        # Look for price patterns in page text
        page_text = await self._page.inner_text("body")
        patterns = [
            r"Current\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"High\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"Winning\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
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
            "[class*='retail']",
            "[class*='msrp']",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            price = self._parse_price(text)
            if price is not None:
                return price

        # Look for MSRP patterns in page text
        page_text = await self._page.inner_text("body")
        patterns = [
            r"MSRP[:\s]*\$?([\d,]+\.?\d*)",
            r"Retail[:\s]*\$?([\d,]+\.?\d*)",
            r"Original\s*Price[:\s]*\$?([\d,]+\.?\d*)",
            r"List\s*Price[:\s]*\$?([\d,]+\.?\d*)",
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

        # Look for condition in page text
        page_text = await self._page.inner_text("body")
        patterns = [
            r"Condition[:\s]*([^\n]+)",
            r"Item\s*Condition[:\s]*([^\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return ""

    async def _get_auction_end(self) -> Optional[str]:
        """Extract auction end datetime."""
        selectors = [
            ".end-time",
            ".auction-end",
            ".closing-time",
            ".time-left",
            "[class*='end']",
            "[class*='closing']",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            dt = self._parse_datetime(text)
            if dt:
                return dt

        # Look for end time patterns
        page_text = await self._page.inner_text("body")
        patterns = [
            r"Ends?[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Closing[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Auction\s*End[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
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

        # Try to find pickup section
        selectors = [
            ".pickup-info",
            ".pickup-location",
            ".pickup-details",
            "[class*='pickup']",
            "#pickup",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text:
                # Try to parse location and dates from combined text
                if "location" in text.lower() or any(c.isdigit() for c in text):
                    lines = text.split("\n")
                    for line in lines:
                        if any(word in line.lower() for word in ["address", "location", "street", "ave", "road", "blvd"]):
                            location = line.strip()
                        elif any(word in line.lower() for word in ["date", "time", "am", "pm", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]):
                            dates = line.strip() if not dates else f"{dates}; {line.strip()}"

        # Fallback: search in page text
        if not location:
            page_text = await self._page.inner_text("body")
            match = re.search(r"Pickup\s*Location[:\s]*([^\n]+)", page_text, re.IGNORECASE)
            if match:
                location = match.group(1).strip()

        if not dates:
            page_text = await self._page.inner_text("body")
            match = re.search(r"Pickup\s*(?:Date|Time)s?[:\s]*([^\n]+)", page_text, re.IGNORECASE)
            if match:
                dates = match.group(1).strip()

        return location, dates

    async def _get_images(self) -> list[str]:
        """Extract all image URLs for the item."""
        image_urls = []

        # Common image selectors
        selectors = [
            ".item-images img",
            ".product-images img",
            ".gallery img",
            ".item-gallery img",
            ".photo-gallery img",
            "[class*='gallery'] img",
            "[class*='image'] img",
            ".carousel img",
            "#images img",
        ]

        for selector in selectors:
            urls = await self._get_all_attributes(selector, "src")
            for url in urls:
                if url and not url.startswith("data:") and url not in image_urls:
                    # Handle relative URLs
                    full_url = urljoin(self.base_url, url)
                    image_urls.append(full_url)

            # Also check data-src for lazy-loaded images
            urls = await self._get_all_attributes(selector, "data-src")
            for url in urls:
                if url and not url.startswith("data:") and url not in image_urls:
                    full_url = urljoin(self.base_url, url)
                    image_urls.append(full_url)

        # If no images found in galleries, look for main product image
        if not image_urls:
            main_img = await self._safe_get_attribute("img.main-image, img.product-image, img#main-image", "src")
            if main_img and not main_img.startswith("data:"):
                image_urls.append(urljoin(self.base_url, main_img))

        return image_urls[:10]  # Limit to 10 images
