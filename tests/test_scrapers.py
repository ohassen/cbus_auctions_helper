"""Tests for scraper modules."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.scrapers.base import BaseScraper, ScraperConfig
from src.scrapers.capital_city import CapitalCityScraper
from src.scrapers.bidfta import BidFTAScraper, COLUMBUS_CITIES, COLUMBUS_ZIP_PREFIXES


class TestScraperConfig:
    """Tests for ScraperConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ScraperConfig()

        assert config.rate_limit_delay == 0.5
        assert config.max_retries == 3
        assert config.timeout == 30000
        assert config.headless is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = ScraperConfig(
            rate_limit_delay=1.0,
            max_retries=5,
            timeout=60000,
            headless=False
        )

        assert config.rate_limit_delay == 1.0
        assert config.max_retries == 5


class TestBaseScraper:
    """Tests for BaseScraper utility methods."""

    def test_parse_price_valid(self):
        """Test parsing valid price strings."""
        scraper = CapitalCityScraper.__new__(CapitalCityScraper)

        assert scraper._parse_price("$45.99") == 45.99
        assert scraper._parse_price("$1,234.56") == 1234.56
        assert scraper._parse_price("45.99") == 45.99
        assert scraper._parse_price("$0.99") == 0.99

    def test_parse_price_invalid(self):
        """Test parsing invalid price strings."""
        scraper = CapitalCityScraper.__new__(CapitalCityScraper)

        assert scraper._parse_price("") is None
        assert scraper._parse_price("N/A") is None
        assert scraper._parse_price(None) is None

    def test_parse_datetime_valid(self):
        """Test parsing valid datetime strings."""
        scraper = CapitalCityScraper.__new__(CapitalCityScraper)

        dt = scraper._parse_datetime("01/15/2025 2:30 PM")
        assert dt is not None
        assert dt.month == 1
        assert dt.day == 15
        assert dt.year == 2025

    def test_parse_datetime_invalid(self):
        """Test parsing invalid datetime strings."""
        scraper = CapitalCityScraper.__new__(CapitalCityScraper)

        assert scraper._parse_datetime("") is None
        assert scraper._parse_datetime("invalid") is None
        assert scraper._parse_datetime(None) is None


class TestCapitalCityScraper:
    """Tests for Capital City scraper."""

    def test_extract_id_from_url(self):
        """Test extracting item ID from URL."""
        scraper = CapitalCityScraper.__new__(CapitalCityScraper)

        assert scraper._extract_id_from_url("https://example.com/lot/12345") == "12345"
        assert scraper._extract_id_from_url("https://example.com?id=67890") == "67890"
        assert scraper._extract_id_from_url("https://example.com/item-99999") == "99999"

    def test_scraper_name(self):
        """Test scraper name property."""
        assert CapitalCityScraper.name == "capital_city"

    def test_base_url(self):
        """Test base URL property."""
        assert CapitalCityScraper.base_url == "https://capitalcityonlineauction.com"


class TestBidFTAScraper:
    """Tests for BidFTA scraper."""

    def test_is_columbus_location_valid(self):
        """Test Columbus location detection with valid locations."""
        scraper = BidFTAScraper.__new__(BidFTAScraper)

        assert scraper._is_columbus_location("Columbus, OH 43215") is True
        assert scraper._is_columbus_location("Westerville Warehouse") is True
        assert scraper._is_columbus_location("Grove City Distribution Center") is True
        assert scraper._is_columbus_location("123 Main St, Dublin, OH") is True
        assert scraper._is_columbus_location("Warehouse - 43201") is True

    def test_is_columbus_location_invalid(self):
        """Test Columbus location detection with invalid locations."""
        scraper = BidFTAScraper.__new__(BidFTAScraper)

        assert scraper._is_columbus_location("Cleveland, OH") is False
        assert scraper._is_columbus_location("Cincinnati Facility") is False
        assert scraper._is_columbus_location("Toledo, OH 43601") is False
        assert scraper._is_columbus_location("") is False

    def test_scraper_name(self):
        """Test scraper name property."""
        assert BidFTAScraper.name == "bidfta"

    def test_base_url(self):
        """Test base URL property."""
        assert BidFTAScraper.base_url == "https://www.bidfta.com"

    def test_columbus_locations_list(self):
        """Test that Columbus locations list contains expected values."""
        assert "columbus" in COLUMBUS_CITIES
        assert "westerville" in COLUMBUS_CITIES
        assert "dublin" in COLUMBUS_CITIES
        assert "432" in COLUMBUS_ZIP_PREFIXES  # Columbus ZIP prefix


class TestScraperIntegration:
    """Integration-style tests with mocked browser."""

    @pytest.mark.asyncio
    async def test_capital_city_context_manager(self):
        """Test scraper can be used as async context manager."""
        with patch.object(CapitalCityScraper, 'start', new_callable=AsyncMock):
            with patch.object(CapitalCityScraper, 'stop', new_callable=AsyncMock):
                async with CapitalCityScraper() as scraper:
                    assert scraper is not None

    @pytest.mark.asyncio
    async def test_bidfta_context_manager(self):
        """Test scraper can be used as async context manager."""
        with patch.object(BidFTAScraper, 'start', new_callable=AsyncMock):
            with patch.object(BidFTAScraper, 'stop', new_callable=AsyncMock):
                async with BidFTAScraper() as scraper:
                    assert scraper is not None


class TestMockScraping:
    """Tests using mocked page responses."""

    @pytest.fixture
    def mock_page(self):
        """Create a mock Playwright page."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[])
        page.inner_text = AsyncMock(return_value="")
        page.wait_for_selector = AsyncMock()
        page.set_default_timeout = MagicMock()
        return page

    @pytest.mark.asyncio
    async def test_scrape_listing_no_title(self, mock_page):
        """Test that scraping fails gracefully when no title found."""
        scraper = CapitalCityScraper.__new__(CapitalCityScraper)
        scraper._page = mock_page
        scraper.config = ScraperConfig()

        mock_page.inner_text.return_value = ""
        mock_page.query_selector.return_value = None

        result = await scraper.scrape_listing("https://example.com/lot/123", "search-001")

        # Should return None when no title found
        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """Test that rate limiting delay is applied."""
        import asyncio
        import time

        scraper = CapitalCityScraper.__new__(CapitalCityScraper)
        scraper.config = ScraperConfig(rate_limit_delay=0.1)

        start = time.time()
        await scraper._rate_limit()
        elapsed = time.time() - start

        assert elapsed >= 0.1
