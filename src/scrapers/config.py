"""Configuration for scraper selectors and constants."""

from typing import Dict, List

# Timeout constants (milliseconds)
TIMEOUT_PAGE_LOAD = 30000
TIMEOUT_CONTENT_WAIT = 15000
TIMEOUT_SHORT = 5000

# Rate limiting
DEFAULT_RATE_LIMIT_DELAY = 0.5  # seconds between requests

# Scraping limits
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_IMAGES = 10
DEFAULT_MAX_PAGES_CAPITAL_CITY = 5
DEFAULT_MAX_PAGES_BIDFTA = 10

# Selectors organized by field type and site
SELECTORS: Dict[str, Dict[str, List[str]]] = {
    "title": {
        "common": [
            "h1",
            "h2",
            ".item-title",
            ".lot-title",
            ".product-title",
            ".auction-title",
            ".item-name",
            ".product-name",
            ".lot-name",
            "[class*='title'] h1",
            "[class*='title'] h2",
            "[class*='Title']",
            "[class*='name']",
            ".detail-title",
            ".details h1",
            ".details h2",
            "#itemTitle",
            "#lotTitle",
            ".card-title",
            ".listing-title",
        ],
        "bidfta": [
            "h1.lot-title",
            "h1.item-title",
            "h1.product-title",
            "h1[class*='title']",
            "h1[class*='Title']",
            ".lot-details h1",
            ".item-details h1",
            ".MuiTypography-h1",
            ".MuiTypography-h2",
        ],
    },
    "description": {
        "common": [
            ".item-description",
            ".lot-description",
            ".product-description",
            "#description",
            "[class*='description']",
            ".details-text",
            ".detail-description",
            ".details-content",
        ],
    },
    "current_price": {
        "common": [
            ".current-bid",
            ".current-price",
            ".high-bid",
            ".winning-bid",
            ".bid-amount",
            "[class*='current'][class*='bid']",
            "[class*='price']",
        ],
    },
    "msrp": {
        "common": [
            ".msrp",
            ".retail-price",
            ".original-price",
            "[class*='retail']",
            "[class*='msrp']",
        ],
        "bidfta": [
            ".msrp",
            ".retail-price",
            ".original-price",
            ".list-price",
            "[class*='msrp']",
            "[class*='retail']",
        ],
    },
    "condition": {
        "common": [
            ".condition",
            ".item-condition",
            "[class*='condition']",
        ],
    },
    "auction_end": {
        "common": [
            ".end-time",
            ".auction-end",
            ".closing-time",
            ".countdown",
            "[class*='end-time']",
            "[class*='EndTime']",
            "[class*='auction-end']",
            "[class*='closing']",
            "[class*='Closing']",
            ".time-remaining",
            "[class*='TimeRemaining']",
        ],
        "bidfta": [
            ".end-time",
            ".auction-end",
            ".closing-time",
            ".countdown",
            "[class*='end']",
            "[class*='closing']",
            "[class*='countdown']",
        ],
    },
    "status": {
        "common": [
            ".status",
            ".auction-status",
            ".item-status",
            ".badge",
            ".label",
            "[class*='status']",
            "[class*='badge']",
            "[class*='label']",
        ],
        "bidfta": [
            ".status",
            ".auction-status",
            ".item-status",
            ".badge",
            ".label",
            "[class*='status']",
            "[class*='badge']",
            "[class*='label']",
            ".MuiChip-label",
            ".MuiBadge-badge",
        ],
    },
    "images": {
        "common": [
            ".item-images img",
            ".product-images img",
            ".gallery img",
            "[class*='gallery'] img",
            "[class*='image'] img",
            ".carousel img",
            ".slider img",
            "img[class*='product']",
            "img[class*='item']",
        ],
        "bidfta": [
            ".lot-images img",
            ".item-images img",
            ".product-gallery img",
            ".image-gallery img",
            ".carousel img",
            "[class*='gallery'] img",
            "[class*='image-container'] img",
            ".slick-slide img",
            ".swiper-slide img",
        ],
    },
    "pickup_info": {
        "bidfta": [
            ".pickup-info",
            ".pickup-location",
            ".facility-info",
            ".warehouse-info",
            "[class*='pickup']",
            "[class*='facility']",
        ],
    },
}

# Regex patterns for text extraction
PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "current_price": {
        "common": [
            r"Current\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"High\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"Winning\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"Price[:\s]*\$?([\d,]+\.?\d*)",
        ],
        "bidfta": [
            r"Current\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"High\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
            r"Your\s*Bid[:\s]*\$?([\d,]+\.?\d*)",
        ],
    },
    "msrp": {
        "common": [
            r"MSRP[:\s]*\$?([\d,]+\.?\d*)",
            r"Retail[:\s]*\$?([\d,]+\.?\d*)",
            r"Original\s*Price[:\s]*\$?([\d,]+\.?\d*)",
        ],
        "bidfta": [
            r"MSRP[:\s]*\$?([\d,]+\.?\d*)",
            r"Retail(?:\s*Value)?[:\s]*\$?([\d,]+\.?\d*)",
            r"Original\s*Price[:\s]*\$?([\d,]+\.?\d*)",
            r"List\s*Price[:\s]*\$?([\d,]+\.?\d*)",
            r"Value[:\s]*\$?([\d,]+\.?\d*)",
        ],
    },
    "condition": {
        "common": [
            r"Condition[:\s]*([^\n]+)",
        ],
    },
    "auction_end": {
        "common": [
            r"Auction\s*Ends?[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Ends?[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Closing[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Closes[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"End\s*Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Bidding\s*Ends?[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
        ],
        "bidfta": [
            r"Ends?[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Closing[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Auction\s*End[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
            r"Closes[:\s]*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M?)",
        ],
    },
    "pickup_location": {
        "common": [
            r"Pickup\s*Location[:\s]*([^\n]+)",
            r"(?:Facility|Warehouse|Location)[:\s]*([^\n]+)",
        ],
    },
    "pickup_dates": {
        "common": [
            r"Pickup\s*(?:Date|Time|Hour)s?[:\s]*([^\n]+)",
        ],
    },
    "id": {
        "common": [
            r"AuctionItemId=([^&]+)",
            r"ItemId=([^&]+)",
            r"id=([^&]+)",
            r"lot[_-]?(\d+)",
            r"item[_-]?(\d+)",
            r"/(\d+)/?$",
        ],
        "bidfta": [
            r"lot[_/-]?(\d+)",
            r"item[_/-]?(\d+)",
            r"/(\d+)/?$",
            r"id=(\d+)",
            r"lotId=(\d+)",
        ],
    },
}

# Sold/closed indicators
SOLD_INDICATORS = [
    "sold",
    "closed",
    "auction ended",
    "auction closed",
    "no longer available",
    "has ended",
    "bidding closed",
    "winning bidder",
    "sold out",
]

# Invalid title patterns
INVALID_TITLES = [
    "capital city online auction",
    "capital city auction",
    "online auction",
    "home",
    "search results",
    "no title",
    "untitled",
]

INVALID_TITLE_PREFIXES = [
    "about this item",
    "product details",
    "item details",
    "description",
    "features",
]

# Generic navigation terms to filter out
NAVIGATION_TERMS = ["home", "back", "search", "login", "register"]

# Image attributes to check
IMAGE_ATTRIBUTES = ["src", "data-src", "data-lazy"]


def get_selectors(field: str, site: str = None) -> List[str]:
    """Get selectors for a field, combining common and site-specific ones.

    Args:
        field: Field name (e.g., 'title', 'description')
        site: Site name (e.g., 'bidfta', 'capital_city'), or None for common only

    Returns:
        List of CSS selectors to try
    """
    field_selectors = SELECTORS.get(field, {})
    selectors = field_selectors.get("common", []).copy()

    if site and site in field_selectors:
        # Add site-specific selectors first (higher priority)
        selectors = field_selectors[site] + selectors

    return selectors


def get_patterns(field: str, site: str = None) -> List[str]:
    """Get regex patterns for a field, combining common and site-specific ones.

    Args:
        field: Field name (e.g., 'current_price', 'auction_end')
        site: Site name (e.g., 'bidfta', 'capital_city'), or None for common only

    Returns:
        List of regex patterns to try
    """
    field_patterns = PATTERNS.get(field, {})
    patterns = field_patterns.get("common", []).copy()

    if site and site in field_patterns:
        # Add site-specific patterns first (higher priority)
        patterns = field_patterns[site] + patterns

    return patterns
