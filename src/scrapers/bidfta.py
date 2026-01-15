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

    async def _is_item_sold_or_closed(self) -> bool:
        """Check if the item is sold, closed, or no longer available."""
        page_text = await self._page.inner_text("body")
        page_text_lower = page_text.lower()

        # Common indicators that an auction is sold/closed/ended
        sold_indicators = [
            "sold",
            "closed",
            "auction ended",
            "auction closed",
            "no longer available",
            "has ended",
            "bidding closed",
            "winning bidder",
            "sold out"
        ]

        # Check if any sold indicator appears in the page
        if any(indicator in page_text_lower for indicator in sold_indicators):
            # Look for these terms in prominent locations (status, badges, etc.)
            status_selectors = [
                ".status", ".auction-status", ".item-status",
                ".badge", ".label", "[class*='status']",
                "[class*='badge']", "[class*='label']",
                ".MuiChip-label", ".MuiBadge-badge"  # Material-UI components
            ]

            for selector in status_selectors:
                status_text = await self._safe_get_text(selector)
                if status_text:
                    status_lower = status_text.lower()
                    if any(indicator in status_lower for indicator in sold_indicators):
                        logger.info(f"Item is sold/closed (status: {status_text})")
                        return True

        return False

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
        # Try standard selectors first
        selectors = [
            "h1.lot-title",
            "h1.item-title",
            "h1.product-title",
            "h1[class*='title']",
            "h1[class*='Title']",
            ".lot-details h1",
            ".item-details h1",
            ".MuiTypography-h1",
            ".MuiTypography-h2",
            "h1",
            "h2",
        ]
        for selector in selectors:
            title = await self._safe_get_text(selector)
            if title and len(title) > 3:
                logger.debug(f"BidFTA: Found title via selector '{selector}': {title[:50]}")
                return title

        # Fallback: use JavaScript to find any prominent heading
        try:
            title = await self._page.evaluate('''
                () => {
                    // Try various heading elements
                    const h1 = document.querySelector('h1');
                    if (h1 && h1.innerText.trim()) return h1.innerText.trim();

                    const h2 = document.querySelector('h2');
                    if (h2 && h2.innerText.trim()) return h2.innerText.trim();

                    // Try meta tags (OpenGraph, etc)
                    const ogTitle = document.querySelector('meta[property="og:title"]');
                    if (ogTitle && ogTitle.content) return ogTitle.content.trim();

                    const metaTitle = document.querySelector('meta[name="title"]');
                    if (metaTitle && metaTitle.content) return metaTitle.content.trim();

                    // Try to find any element with "title" in class or id
                    const titleEls = document.querySelectorAll('[class*="title" i], [class*="Title"], [id*="title" i]');
                    for (const el of titleEls) {
                        const text = el.innerText?.trim();
                        if (text && text.length > 3 && text.length < 200) {
                            return text;
                        }
                    }

                    // Last resort: look for any large text near the top
                    const allText = document.querySelectorAll('div, span, p');
                    for (const el of allText) {
                        const text = el.innerText?.trim();
                        // Look for text that's not too long, not too short
                        if (text && text.length > 10 && text.length < 150 &&
                            !text.includes('\\n') && el.offsetTop < 500) {
                            return text;
                        }
                    }

                    return null;
                }
            ''')
            if title and len(title) > 3:
                logger.debug(f"BidFTA: Found title via JavaScript: {title[:50]}")
                return title
        except Exception as e:
            logger.debug(f"BidFTA: JavaScript title extraction failed: {e}")

        logger.warning(f"BidFTA: Could not find title after trying all methods")
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
