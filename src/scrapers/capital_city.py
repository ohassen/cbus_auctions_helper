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

            # Verify search worked by checking URL or page content
            current_url = self._page.url
            logger.info(f"After search, URL is: {current_url}")

            # Check if we got a "no results" message
            page_text = await self._page.inner_text("body")
            no_results_indicators = [
                "no results found",
                "0 results",
                "no items found",
                "no matches",
                "try a different search"
            ]
            if any(indicator in page_text.lower() for indicator in no_results_indicators):
                logger.info(f"Search returned no results for '{search_term}'")
                return

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

                # Log first few URLs for debugging
                if listing_links:
                    logger.debug(f"Sample URLs: {listing_links[:3]}")

                for url in listing_links:
                    logger.debug(f"Yielding listing URL: {url}")
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

    def _is_valid_listing_url(self, url: str) -> bool:
        """Check if URL is a valid listing page (not navigation, footer, etc)."""
        url_lower = url.lower()

        # Must contain item/lot/auction detail patterns
        if not any(pattern in url_lower for pattern in ['auctionitemdetail', 'itemdetail', 'item-detail', 'lotdetail', 'lot-detail']):
            return False

        # Exclude navigation and other non-listing pages
        exclude_patterns = [
            'login', 'register', 'signup', 'signin',
            'cart', 'checkout', 'account', 'profile',
            'about', 'contact', 'help', 'faq',
            'terms', 'privacy', 'policy',
            'search', 'browse', 'category',
            '/home', '/index'
        ]

        if any(pattern in url_lower for pattern in exclude_patterns):
            return False

        # Must have query parameters or path segments (real item IDs)
        if '?' not in url and url.count('/') < 4:
            return False

        return True

    async def _find_listing_links(self) -> list[str]:
        """Find all listing links on the current page."""
        listing_links = []

        # Strategy 1: Links to AuctionItemDetail pages (most specific)
        links = await self._page.query_selector_all("a[href*='AuctionItemDetail'], a[href*='ItemDetail'], a[href*='item-detail']")
        for link in links:
            href = await link.get_attribute("href")
            if href:
                full_url = urljoin(self.base_url, href)
                if self._is_valid_listing_url(full_url):
                    listing_links.append(full_url)

        # Strategy 2: Product cards/tiles with links
        if not listing_links:
            selectors = [
                ".auction-item a",
                ".lot-item a",
                ".product-card a",
                ".item-card a",
                ".listing-item a",
            ]
            for selector in selectors:
                try:
                    cards = await self._page.query_selector_all(selector)
                    for card in cards:
                        href = await card.get_attribute("href")
                        if href and href != "#":
                            full_url = urljoin(self.base_url, href)
                            if self._is_valid_listing_url(full_url) and full_url not in listing_links:
                                listing_links.append(full_url)
                except (PlaywrightTimeout, Exception) as e:
                    logger.debug(f"Error finding links with selector '{selector}': {e}")
                    continue

        # Deduplicate while preserving order
        seen = set()
        unique_links = []
        for link in listing_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        logger.debug(f"Found {len(unique_links)} valid listing URLs")
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
            except (PlaywrightTimeout, Exception) as e:
                logger.debug(f"Error checking next button with selector '{selector}': {e}")
                continue

        return False

    async def scrape_listing(self, url: str, search_id: str) -> Optional[AuctionItem]:
        """Scrape a single listing page."""
        try:
            logger.debug(f"Scraping listing: {url}")
            await self._page.goto(url, wait_until="networkidle")
            await asyncio.sleep(3)  # Capital City needs more time for JS rendering

            # Wait for page content to be ready
            try:
                await self._page.wait_for_selector("body", timeout=5000)
            except PlaywrightTimeout:
                pass

            # Check if item is sold/closed - skip if so
            if await self._is_item_sold_or_closed():
                logger.info(f"Skipping sold/closed item: {url}")
                return None

            # Extract external ID from URL
            external_id = self._extract_id_from_url(url)

            # Title - try multiple selectors
            title = await self._get_title()
            if not title:
                logger.warning(f"Could not find title for {url}")
                return None

            # Validate title - reject generic/invalid titles
            title_lower = title.lower()
            invalid_titles = [
                'capital city online auction',
                'capital city auction',
                'online auction',
                'home',
                'search results',
                'no title',
                'untitled'
            ]

            # Also reject titles that are just generic text or fragments
            invalid_prefixes = [
                'about this item',
                'product details',
                'item details',
                'description',
                'features'
            ]

            if any(invalid in title_lower for invalid in invalid_titles):
                logger.info(f"Skipping item with invalid title: {title}")
                return None

            if any(title_lower.startswith(prefix) for prefix in invalid_prefixes):
                logger.info(f"Skipping item with generic title prefix: {title}")
                return None

            # Skip if title is too short (likely not a real item)
            if len(title) < 10:
                logger.info(f"Skipping item with too-short title: {title}")
                return None

            # Skip titles that start with special characters or markers
            if title.startswith(('***', '---', '===', '>>>', '<<<')):
                logger.info(f"Skipping item with marker prefix: {title}")
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

    # All field extraction methods are now inherited from BaseScraper
    # Site-specific customization is done via config.py selectors and patterns
