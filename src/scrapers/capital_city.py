"""Scraper for Capital City Online Auction (capitalcityonlineauction.com)."""

import asyncio
import json
import logging
import os
import re
from typing import Optional, AsyncIterator
from urllib.parse import urljoin, urlencode, quote

from openai import OpenAI
from playwright.async_api import TimeoutError as PlaywrightTimeout

from .base import BaseScraper, ScraperConfig
from ..database import AuctionItem

logger = logging.getLogger(__name__)

# Cache for key term extraction to avoid repeated API calls
_KEY_TERM_CACHE = {}


def extract_key_term(query: str) -> str:
    """
    Use Claude to extract the key term (essence) from a search query.

    Examples:
        "office chair" -> "chair"
        "manual coffee grinder" -> "grinder"
        "stainless steel pan" -> "pan"

    The key term is the fundamental item type, not the modifiers.
    """
    # Check cache first
    if query in _KEY_TERM_CACHE:
        return _KEY_TERM_CACHE[query]

    try:
        api_key = os.getenv("OPEN_ROUTER_API_KEY")
        if not api_key:
            logger.warning("OPEN_ROUTER_API_KEY not set, falling back to simple extraction")
            return _fallback_key_term_extraction(query)

        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

        prompt = f"""Extract the best search keyword from this product query for an auction website search.

The keyword should be the most SPECIFIC and DISTINCTIVE word or phrase that reliably finds THIS product on auction sites.
Choose the term that uniquely identifies the product category — it is NOT always the last noun.

Examples:
- "office chair" -> "chair" (finds all chair types; "office" is a modifier handled by semantic matching)
- "gooseneck kettle" -> "kettle" (specific product type)
- "stainless steel pan" -> "pan" (specific product type)
- "vacuum cleaner" -> "vacuum" (NOT "cleaner" — "cleaner" alone matches unrelated cleaning products)
- "bread maker" -> "bread maker" (NOT "maker" — "maker" alone matches coffee makers, waffle makers, etc.)
- "manual coffee grinder" -> "coffee grinder" (NOT just "grinder" — "grinder" alone matches angle/meat grinders)
- "garage opener" -> "garage opener" (both words needed to be specific)
- "air purifier" -> "air purifier" (both words needed)

Key rule: if the last word alone (e.g. "cleaner", "maker", "grinder", "machine", "device") would
match many UNRELATED products, use the full phrase or the more specific first word instead.

Query: "{query}"

Respond with ONLY the search keyword (1-3 words max), nothing else."""

        response = client.chat.completions.create(
            model="google/gemini-2.0-flash-001",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}]
        )

        key_term = response.choices[0].message.content.strip().lower()

        # Cache the result
        _KEY_TERM_CACHE[query] = key_term
        logger.info(f"Extracted key term from '{query}': '{key_term}'")

        return key_term

    except Exception as e:
        logger.warning(f"Error extracting key term with Claude: {e}, falling back to simple extraction")
        return _fallback_key_term_extraction(query)


def _fallback_key_term_extraction(query: str) -> str:
    """Fallback key term extraction if Claude API fails."""
    # Remove common filler words
    stop_words = {'with', 'and', 'or', 'the', 'a', 'an', 'for', 'in', 'on', 'of', 'manual', 'electric', 'automatic'}
    words = [w.lower() for w in query.split() if w.lower() not in stop_words]

    # Generic nouns that are too broad to use alone as search terms.
    # e.g. "cleaner" finds floor cleaners/sprays, "maker" finds coffee/waffle/candle makers,
    # "grinder" finds angle/meat grinders — none of these find the intended product.
    # In these cases use the full 2-word compound phrase for a specific search.
    too_generic = {'cleaner', 'cleaners', 'maker', 'makers', 'grinder', 'grinders',
                   'machine', 'machines', 'device', 'devices',
                   'appliance', 'appliances', 'tool', 'tools', 'unit', 'units',
                   'system', 'systems', 'set', 'kit'}

    if len(words) >= 2:
        last_word = words[-1]
        if last_word in too_generic:
            # Use the full 2-word compound phrase — specific enough to find the right product.
            # e.g. "bread maker" (not just "bread" or "maker"),
            #      "vacuum cleaner" (better than "cleaner" alone; "vacuum" alone also works but this is safe)
            #      "coffee grinder" (not just "coffee" or "grinder")
            return f"{words[0]} {last_word}"
        return words[-1]  # e.g., "chair" from "office chair"
    elif len(words) == 1:
        return words[0]
    else:
        return query.lower()


def extract_search_terms(query: str) -> list[str]:
    """
    Extract search terms using semantic key term extraction.

    Strategy: Search ONLY for the key term (essence) to cast the widest net,
    then rely on semantic matching to filter results to the original query intent.

    Examples:
        "office chair" -> ["chair"]
        "manual coffee grinder" -> ["grinder"]
        "stainless steel pan" -> ["pan"]

    This broad search captures all item variations (desk chair, task chair, etc.),
    then semantic matching filters to only items matching the original query.
    """
    # Extract and return only the key term (essence)
    key_term = extract_key_term(query)
    return [key_term]


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

            await self._rate_limit()

        logger.info(f"Found {len(self._found_urls)} total unique items across all search terms")

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
