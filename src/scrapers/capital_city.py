"""Scraper for Capital City Online Auction (capitalcityonlineauction.com)."""

import asyncio
import logging
import re
from typing import Optional, AsyncIterator
from urllib.parse import urljoin, urlencode, quote

from playwright.async_api import TimeoutError as PlaywrightTimeout

from .base import BaseScraper, ScraperConfig
from ..database import AuctionItem

logger = logging.getLogger(__name__)


def extract_search_terms(query: str) -> list[str]:
    """
    Extract simple search terms from a complex query.

    For "office chair with mesh seat" -> ["office chair", "chair"]
    For "stainless steel cooking pan" -> ["stainless steel pan", "pan", "cookware"]

    Returns multiple search terms to try, from most specific to least.
    """
    # Remove common filler words
    stop_words = {'with', 'and', 'or', 'the', 'a', 'an', 'for', 'in', 'on', 'of'}
    words = [w.lower() for w in query.split() if w.lower() not in stop_words]

    search_terms = []

    # Try the first two words together
    if len(words) >= 2:
        search_terms.append(f"{words[0]} {words[1]}")

    # Try just the main noun (usually last significant word or second word)
    if len(words) >= 2:
        search_terms.append(words[1])  # e.g., "chair" from "office chair"

    if len(words) >= 1:
        search_terms.append(words[0])  # e.g., "office"

    # If query contains specific item types, add them
    item_types = ['chair', 'desk', 'table', 'pan', 'pot', 'cookware', 'furniture', 'electronics']
    for item_type in item_types:
        if item_type in query.lower() and item_type not in search_terms:
            search_terms.append(item_type)

    return search_terms[:3]  # Return top 3 search terms


class CapitalCityScraper(BaseScraper):
    """Scraper for Capital City Online Auction."""

    name = "capital_city"
    base_url = "https://capitalcityonlineauction.com"

    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config)
        self._found_urls = set()  # Track URLs across search terms to avoid duplicates

    async def search(self, query: str) -> AsyncIterator[str]:
        """Search for items and yield listing URLs."""
        self._found_urls = set()

        # Extract simple search terms from the complex query
        search_terms = extract_search_terms(query)
        logger.info(f"Query '{query}' -> search terms: {search_terms}")

        for search_term in search_terms:
            async for url in self._search_term(search_term):
                if url not in self._found_urls:
                    self._found_urls.add(url)
                    yield url

            # If we found items with a term, don't try less specific terms
            if self._found_urls:
                logger.info(f"Found {len(self._found_urls)} items with term '{search_term}'")
                break

            await self._rate_limit()

    async def _search_term(self, search_term: str) -> AsyncIterator[str]:
        """Search for a single term and yield listing URLs using the site's search form."""
        try:
            # Navigate to the main page
            logger.info(f"Navigating to {self.base_url} to search for '{search_term}'")
            await self._page.goto(self.base_url, wait_until="networkidle")
            await asyncio.sleep(1)

            # Find and use the search form - try multiple approaches
            search_input = None
            search_selectors = [
                "input[type='search']",
                "input[name='searchText']",
                "input[name='search']",
                "input[name='q']",
                "input[placeholder*='search' i]",
                "input[placeholder*='Search' i]",
                "#searchText",
                "#search",
                ".search-input",
                "[class*='search'] input[type='text']",
                "input.form-control[type='text']",
            ]

            for selector in search_selectors:
                try:
                    search_input = await self._page.query_selector(selector)
                    if search_input:
                        is_visible = await search_input.is_visible()
                        if is_visible:
                            logger.info(f"Found search input with selector: {selector}")
                            break
                        search_input = None
                except Exception:
                    continue

            if not search_input:
                # Try to find any visible text input
                inputs = await self._page.query_selector_all("input[type='text']")
                for inp in inputs:
                    try:
                        if await inp.is_visible():
                            search_input = inp
                            logger.info("Found visible text input as fallback")
                            break
                    except Exception:
                        continue

            if not search_input:
                logger.warning("Could not find search input on Capital City page")
                return

            # Clear and type the search term
            await search_input.click()
            await search_input.fill("")
            await search_input.type(search_term, delay=50)
            await asyncio.sleep(0.5)

            # Submit the search - try pressing Enter or clicking a search button
            await search_input.press("Enter")

            # Wait for navigation/results
            try:
                await self._page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeout:
                logger.warning("Timeout waiting for search results")

            await asyncio.sleep(2)  # Extra time for JS rendering

            # Now scrape the results
            page_num = 1
            max_pages = 5

            while page_num <= max_pages:
                logger.info(f"Scraping search results page {page_num}")

                # Find listing links
                listing_links = await self._find_listing_links()

                if not listing_links:
                    if page_num == 1:
                        logger.info(f"No listings found for search term '{search_term}'")
                    break

                logger.info(f"Found {len(listing_links)} listings on page {page_num}")

                for url in listing_links:
                    yield url

                # Check for next page
                has_next = await self._has_next_page()
                if not has_next:
                    break

                # Click next page
                next_clicked = await self._click_next_page()
                if not next_clicked:
                    break

                page_num += 1
                await asyncio.sleep(1.5)

        except PlaywrightTimeout:
            logger.warning(f"Timeout during search for '{search_term}'")
        except Exception as e:
            logger.error(f"Error during search for '{search_term}': {e}")

    async def _click_next_page(self) -> bool:
        """Click the next page button and wait for navigation."""
        next_selectors = [
            "a:has-text('Next')",
            "a:has-text('>')",
            "a:has-text('›')",
            ".pagination-next",
            "a.next",
            "[aria-label='Next']",
            ".page-link:has-text('Next')",
            "li.next a",
        ]

        for selector in next_selectors:
            try:
                next_button = await self._page.query_selector(selector)
                if next_button:
                    is_disabled = await next_button.get_attribute("disabled")
                    aria_disabled = await next_button.get_attribute("aria-disabled")
                    classes = await next_button.get_attribute("class") or ""

                    if not is_disabled and aria_disabled != "true" and "disabled" not in classes:
                        await next_button.click()
                        await self._page.wait_for_load_state("networkidle", timeout=10000)
                        await asyncio.sleep(1)
                        return True
            except Exception:
                continue

        return False

    async def _find_listing_links(self) -> list[str]:
        """Find all listing links on the current page."""
        listing_links = []

        # Strategy 1: Links to AuctionItemDetail pages
        links = await self._page.query_selector_all("a[href*='AuctionItemDetail'], a[href*='ItemDetail'], a[href*='item-detail']")
        for link in links:
            href = await link.get_attribute("href")
            if href:
                listing_links.append(urljoin(self.base_url, href))

        # Strategy 2: Links with lot/item/auction in URL
        if not listing_links:
            links = await self._page.query_selector_all("a[href*='lot'], a[href*='item'], a[href*='auction']")
            for link in links:
                href = await link.get_attribute("href")
                if href and any(x in href.lower() for x in ['detail', 'view', 'lot', 'item']):
                    full_url = urljoin(self.base_url, href)
                    if full_url not in listing_links:
                        listing_links.append(full_url)

        # Strategy 3: Product cards/tiles with links
        if not listing_links:
            selectors = [
                ".auction-item a",
                ".lot-item a",
                ".product-card a",
                ".item-card a",
                ".listing-item a",
                "[class*='auction'] a[href]",
                "[class*='item'] a[href]",
                ".card a[href]",
            ]
            for selector in selectors:
                try:
                    cards = await self._page.query_selector_all(selector)
                    for card in cards:
                        href = await card.get_attribute("href")
                        if href and href != "#":
                            full_url = urljoin(self.base_url, href)
                            if full_url not in listing_links:
                                listing_links.append(full_url)
                except:
                    continue

        # Strategy 4: Any link that looks like a product detail page
        if not listing_links:
            all_links = await self._page.query_selector_all("a[href]")
            for link in all_links:
                href = await link.get_attribute("href")
                if href and any(x in href.lower() for x in ['detail', 'product', 'lot', 'item']) \
                   and not any(x in href.lower() for x in ['login', 'register', 'cart', 'account']):
                    full_url = urljoin(self.base_url, href)
                    if full_url not in listing_links and full_url != self.base_url:
                        listing_links.append(full_url)

        # Deduplicate while preserving order
        seen = set()
        unique_links = []
        for link in listing_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        return unique_links[:50]  # Limit to first 50 items

    async def _has_next_page(self) -> bool:
        """Check if there's a next page."""
        next_selectors = [
            "a:has-text('Next')",
            "a:has-text('>')",
            "a:has-text('›')",
            ".pagination-next",
            "a.next",
            "[aria-label='Next']",
        ]

        for selector in next_selectors:
            try:
                next_button = await self._page.query_selector(selector)
                if next_button:
                    is_disabled = await next_button.get_attribute("disabled")
                    aria_disabled = await next_button.get_attribute("aria-disabled")
                    classes = await next_button.get_attribute("class") or ""

                    if not is_disabled and aria_disabled != "true" and "disabled" not in classes:
                        return True
            except:
                continue

        return False

    async def scrape_listing(self, url: str, search_id: str) -> Optional[AuctionItem]:
        """Scrape a single listing page."""
        try:
            logger.debug(f"Scraping listing: {url}")
            await self._page.goto(url, wait_until="networkidle")
            await asyncio.sleep(1)  # Allow JS to render

            # Extract external ID from URL
            external_id = self._extract_id_from_url(url)

            # Title - try multiple selectors
            title = await self._get_title()
            if not title:
                logger.warning(f"Could not find title for {url}")
                return None

            logger.info(f"Found item: {title[:50]}...")

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
        patterns = [
            r"AuctionItemId=([^&]+)",
            r"ItemId=([^&]+)",
            r"id=([^&]+)",
            r"lot[_-]?(\d+)",
            r"item[_-]?(\d+)",
            r"/(\d+)/?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        return str(hash(url))

    async def _get_title(self) -> str:
        """Extract item title."""
        selectors = [
            "h1",
            ".item-title",
            ".lot-title",
            ".product-title",
            ".auction-title",
            "[class*='title'] h1",
            "[class*='title'] h2",
            ".detail-title",
        ]
        for selector in selectors:
            title = await self._safe_get_text(selector)
            if title and len(title) > 3 and len(title) < 500:
                return title.strip()

        # Fallback: try page title
        page_title = await self._page.title()
        if page_title:
            # Remove site name from title
            title = page_title.split("|")[0].split("-")[0].strip()
            if len(title) > 3:
                return title

        return ""

    async def _get_description(self) -> str:
        """Extract item description."""
        selectors = [
            ".item-description",
            ".lot-description",
            ".product-description",
            "#description",
            "[class*='description']",
            ".details-text",
            ".detail-description",
        ]
        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text and len(text) > 20:
                return text[:2000]  # Limit length
        return ""

    async def _get_current_price(self) -> Optional[float]:
        """Extract current bid price."""
        selectors = [
            ".current-bid",
            ".current-price",
            ".high-bid",
            ".winning-bid",
            ".bid-amount",
            "[class*='current'][class*='bid']",
            "[class*='price']",
        ]

        for selector in selectors:
            text = await self._safe_get_text(selector)
            price = self._parse_price(text)
            if price is not None and price > 0:
                return price

        # Look for price patterns in page text
        page_text = await self._page.inner_text("body")
        patterns = [
            r"Current\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"High\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"Winning\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"Price[:\s]*\$?([\d,]+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                price = self._parse_price(match.group(1))
                if price and price > 0:
                    return price

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

        page_text = await self._page.inner_text("body")
        patterns = [
            r"MSRP[:\s]*\$?([\d,]+\.?\d*)",
            r"Retail[:\s]*\$?([\d,]+\.?\d*)",
            r"Original\s*Price[:\s]*\$?([\d,]+\.?\d*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return self._parse_price(match.group(1))

        return None

    async def _get_condition(self) -> str:
        """Extract item condition."""
        selectors = [".condition", ".item-condition", "[class*='condition']"]
        for selector in selectors:
            text = await self._safe_get_text(selector)
            if text:
                return text

        page_text = await self._page.inner_text("body")
        match = re.search(r"Condition[:\s]*([^\n]+)", page_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:100]

        return ""

    async def _get_auction_end(self) -> Optional[str]:
        """Extract auction end datetime."""
        selectors = [".end-time", ".auction-end", ".closing-time", "[class*='end']", "[class*='closing']"]
        for selector in selectors:
            text = await self._safe_get_text(selector)
            dt = self._parse_datetime(text)
            if dt:
                return dt

        page_text = await self._page.inner_text("body")
        patterns = [
            r"Ends?[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Closing[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
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

        page_text = await self._page.inner_text("body")

        loc_match = re.search(r"Pickup\s*Location[:\s]*([^\n]+)", page_text, re.IGNORECASE)
        if loc_match:
            location = loc_match.group(1).strip()

        date_match = re.search(r"Pickup\s*(?:Date|Time)s?[:\s]*([^\n]+)", page_text, re.IGNORECASE)
        if date_match:
            dates = date_match.group(1).strip()

        return location, dates

    async def _get_images(self) -> list[str]:
        """Extract all image URLs for the item."""
        image_urls = []

        selectors = [
            ".item-images img",
            ".product-images img",
            ".gallery img",
            "[class*='gallery'] img",
            "[class*='image'] img",
            ".carousel img",
            ".slider img",
            "img[class*='product']",
            "img[class*='item']",
        ]

        for selector in selectors:
            for attr in ["src", "data-src", "data-lazy"]:
                urls = await self._get_all_attributes(selector, attr)
                for url in urls:
                    if url and not url.startswith("data:") and "placeholder" not in url.lower():
                        full_url = urljoin(self.base_url, url)
                        if full_url not in image_urls:
                            image_urls.append(full_url)

        return image_urls[:10]
