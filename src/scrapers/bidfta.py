"""Scraper for BidFTA.com (Columbus locations only)."""

import asyncio
import logging
import re
from typing import Optional, AsyncIterator
from urllib.parse import urljoin, urlencode, quote_plus

from playwright.async_api import TimeoutError as PlaywrightTimeout

from .base import BaseScraper, ScraperConfig
from .capital_city import extract_search_terms
from ..database import AuctionItem

logger = logging.getLogger(__name__)

# Columbus-area location identifiers (city names)
COLUMBUS_CITIES = [
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
]

# Columbus-area ZIP code prefixes (432xx, 430xx ranges)
COLUMBUS_ZIP_PREFIXES = ["432", "430", "431"]

# BidFTA Columbus-area location IDs (from the URL pattern)
# These are the location IDs that correspond to Columbus area warehouses
COLUMBUS_LOCATION_IDS = ["5", "510", "10"]


class BidFTAScraper(BaseScraper):
    """Scraper for BidFTA.com, filtering for Columbus-area locations."""

    name = "bidfta"
    base_url = "https://www.bidfta.com"

    def __init__(self, config: Optional[ScraperConfig] = None):
        super().__init__(config)
        self._found_urls = set()  # Track URLs across search terms to avoid duplicates
        self._search_page_data = {}  # Store data extracted from search page

    def _is_columbus_location(self, location_text: str) -> bool:
        """Check if a location is in the Columbus area."""
        if not location_text:
            return False
        location_lower = location_text.lower()

        # Check city names
        if any(city in location_lower for city in COLUMBUS_CITIES):
            return True

        # Check ZIP code prefixes (e.g., 432xx, 430xx)
        zip_match = re.search(r'\b(\d{5})\b', location_text)
        if zip_match:
            zip_code = zip_match.group(1)
            if any(zip_code.startswith(prefix) for prefix in COLUMBUS_ZIP_PREFIXES):
                return True

        return False

    async def search(self, query: str) -> AsyncIterator[str]:
        """Search for items and yield listing URLs (Columbus locations only)."""
        self._found_urls = set()

        # Extract simple search terms from the complex query
        search_terms = extract_search_terms(query)
        logger.info(f"BidFTA: Query '{query}' -> search terms: {search_terms}")

        urls_before = 0
        for search_term in search_terms:
            async for url in self._search_term(search_term):
                if url not in self._found_urls:
                    self._found_urls.add(url)
                    yield url

            urls_found_this_term = len(self._found_urls) - urls_before

            # If we found items with a term, don't try less specific terms
            if urls_found_this_term > 0:
                logger.info(f"BidFTA: Found {urls_found_this_term} items with term '{search_term}' (total: {len(self._found_urls)})")
                break
            else:
                logger.info(f"BidFTA: No items found for term '{search_term}', trying next term")

            urls_before = len(self._found_urls)
            await self._rate_limit()

        if len(self._found_urls) == 0:
            logger.warning(f"BidFTA: No items found for any search term in query '{query}'")

    async def _search_term(self, search_term: str) -> AsyncIterator[str]:
        """Search for a single term and yield listing URLs (Columbus locations only)."""
        # Build the correct BidFTA search URL with Columbus location IDs
        # Format: /items?pageId=1&itemSearchKeywords=office+chair&locations=5&locations=510&locations=10
        location_params = "&".join([f"locations={loc_id}" for loc_id in COLUMBUS_LOCATION_IDS])

        page_num = 1
        max_pages = 10  # Safety limit

        while page_num <= max_pages:
            try:
                search_url = f"{self.base_url}/items?pageId={page_num}&itemSearchKeywords={quote_plus(search_term)}&{location_params}"
                logger.info(f"Searching BidFTA: {search_url}")

                await self._page.goto(search_url, wait_until="networkidle")
                await asyncio.sleep(3)  # Allow React to render

                # BidFTA uses React - wait for any content to appear
                try:
                    # Wait for any common item container or grid
                    await self._page.wait_for_selector(
                        ".MuiGrid-item, .MuiCard-root, [class*='item'], [class*='Item'], [class*='card'], [class*='Card'], .col, .grid-item, a[href*='itemDetails']",
                        timeout=15000
                    )
                except PlaywrightTimeout:
                    if page_num == 1:
                        logger.info(f"No items found for search term '{search_term}'")
                    else:
                        logger.info("No more items on page")
                    break

                # Find all listing items - the API already filters for Columbus locations
                items_found = 0

                # First, try to find links directly to item details
                item_links = await self._page.query_selector_all("a[href*='itemDetails']")
                if item_links:
                    logger.info(f"Found {len(item_links)} item links via href pattern")
                    items_found = len(item_links)
                    # Extract all hrefs at once to avoid context destruction
                    for link in item_links:
                        try:
                            href = await link.get_attribute("href")
                            if href:
                                full_url = urljoin(self.base_url, href)
                                logger.debug(f"Yielding BidFTA listing URL: {full_url}")
                                yield full_url
                        except Exception as e:
                            logger.debug(f"Failed to get href from link: {e}")
                            continue
                else:
                    # Try multiple selector strategies for BidFTA's React/MUI components
                    item_selectors = [
                        ".MuiCard-root",
                        ".MuiGrid-item",
                        "[class*='ItemCard']",
                        "[class*='item-card']",
                        "[class*='itemCard']",
                        ".auction-item",
                        ".lot-item",
                        ".product-card",
                        "[class*='lot-card']",
                        ".item-grid-item",
                        "[data-lot-id]",
                        ".search-result-item",
                        ".col-md-3",
                        ".col-lg-3",
                        "[class*='col-']",
                    ]

                    for selector in item_selectors:
                        items = await self._page.query_selector_all(selector)
                        if items and len(items) > 0:
                            # FIX: Extract ALL data from search page using JavaScript
                            items_data = await self._page.evaluate(f'''
                                () => {{
                                    const items = document.querySelectorAll("{selector}");
                                    return Array.from(items).map(item => {{
                                        const link = item.querySelector('a[href*="itemDetails"], a[href*="item"], a[href]');
                                        const titleEl = item.querySelector('h1, h2, h3, h4, [class*="title"], [class*="Title"]');
                                        const priceEl = item.querySelector('[class*="price"], [class*="Price"]');

                                        return {{
                                            url: link?.href || null,
                                            title: titleEl?.innerText?.trim() || null,
                                            price: priceEl?.innerText?.trim() || null,
                                            html: item.innerHTML?.substring(0, 500) || null
                                        }};
                                    }}).filter(item => item.url && item.title);
                                }}
                            ''')

                            if items_data:
                                logger.info(f"Found {len(items_data)} items with data from search page using selector: {selector}")
                                items_found = len(items_data)

                                # Store items_data for later use in scrape_listing
                                self._search_page_data = {item['url']: item for item in items_data}

                                for item_data in items_data:
                                    url = item_data['url']
                                    if url and ('item' in url.lower() or 'lot' in url.lower() or 'details' in url.lower()):
                                        logger.info(f"BidFTA: Found item on search page: {item_data['title'][:50]} at {url}")
                                        yield url
                                break  # Found items with this selector

                logger.info(f"Page {page_num}: {items_found} items found")

                if items_found == 0:
                    break

                # Check for next page - just increment pageId since we control it
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
            logger.debug(f"BidFTA: Scraping listing {url}")

            # FIX: Check if we already have data from search page
            search_page_data = getattr(self, '_search_page_data', {}).get(url)
            if search_page_data and search_page_data.get('title'):
                logger.info(f"BidFTA: Using data from search page for {url}")
                title = search_page_data['title']
                # Use search page data, skip visiting the listing page
                external_id = self._extract_id_from_url(url)

                return AuctionItem(
                    search_id=search_id,
                    source_site=self.name,
                    external_id=external_id,
                    title=title,
                    description="",
                    current_price=None,
                    listing_url=url,
                    pickup_location="Columbus area (from search results)",
                    image_urls=[]
                )

            # BidFTA can be slow to load, but reduce timeout to fit 28-min workflow limit
            await self._page.goto(url, wait_until="networkidle", timeout=20000)  # Reduced from 60s

            # FIX #3: Wait for actual content to appear, not just network idle
            try:
                await self._page.wait_for_function('''
                    () => {
                        // Wait for any heading or substantial text to exist
                        const h1 = document.querySelector('h1');
                        const h2 = document.querySelector('h2');
                        const hasHeading = (h1 && h1.innerText.trim()) || (h2 && h2.innerText.trim());

                        // Also check if page has loaded enough content
                        const bodyText = document.body.innerText || '';
                        const hasContent = bodyText.length > 100;

                        return hasHeading || hasContent;
                    }
                ''', timeout=3000)  # Reduced from 15s
                logger.debug(f"BidFTA: Content fully loaded")
            except Exception as e:
                logger.warning(f"BidFTA: Timeout waiting for content, proceeding anyway: {e}")
                # Continue anyway with extra wait
                await asyncio.sleep(1)  # Reduced from 5s

            # Log page title for debugging
            page_title = await self._page.title()
            logger.debug(f"BidFTA: Page title from browser: {page_title}")

            # Check if item is sold/closed - skip if so
            if await self._is_item_sold_or_closed():
                logger.info(f"BidFTA: Skipping sold/closed item: {url}")
                return None

            # Extract external ID from URL
            external_id = self._extract_id_from_url(url)

            # Title
            title = await self._get_title()
            if not title:
                logger.warning(f"BidFTA: Could not find title with standard methods for {url}")

                # FIX #1: Save HTML for debugging
                try:
                    html = await self._page.content()
                    logger.debug(f"BidFTA: Page HTML snippet: {html[:1000]}")
                except Exception as e:
                    logger.debug(f"BidFTA: Could not get HTML: {e}")

                # Try getting it from page title as fallback
                if page_title and len(page_title) > 3 and "bidfta" not in page_title.lower():
                    title = page_title
                    logger.info(f"BidFTA: Using page title as fallback: {title[:50]}")
                else:
                    # FIX #2: Ultra-permissive - get ANY text from the page
                    try:
                        title = await self._page.evaluate('''
                            () => {
                                // Get ALL text content
                                const allText = document.body.innerText || document.body.textContent || '';
                                const lines = allText.split('\\n')
                                    .map(l => l.trim())
                                    .filter(l => l.length > 10 && l.length < 200)
                                    .filter(l => !l.toLowerCase().includes('cookie'))
                                    .filter(l => !l.toLowerCase().includes('javascript'));

                                // Return the first substantial line
                                return lines[0] || null;
                            }
                        ''')
                        if title:
                            logger.info(f"BidFTA: Using ultra-permissive extraction: {title[:50]}")
                    except Exception as e:
                        logger.error(f"BidFTA: Ultra-permissive extraction failed: {e}")

                    if not title:
                        logger.error(f"BidFTA: All title extraction methods failed for {url}")
                        return None

            logger.debug(f"BidFTA: Title found: {title[:50]}")

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
            logger.debug(f"BidFTA: Checking location for {title[:50]}: '{pickup_location}'")
            if pickup_location and not self._is_columbus_location(pickup_location):
                logger.info(f"BidFTA: Skipping non-Columbus item at '{pickup_location}' - {title[:50]}")
                return None
            elif not pickup_location:
                # If no location found, keep the item (Columbus-filtered by search URL anyway)
                logger.info(f"BidFTA: No location found, keeping item (URL was Columbus-filtered): {title[:50]}")
                pickup_location = "Columbus area (location not specified)"

            # Images
            image_urls = await self._get_images()

            logger.info(f"BidFTA: Successfully scraped item: {title[:50]} at {pickup_location}")
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
            logger.error(f"BidFTA: Error scraping listing {url}: {e}", exc_info=True)
            return None

    # All field extraction methods are now inherited from BaseScraper
    # Site-specific customization is done via config.py selectors and patterns
