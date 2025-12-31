"""Tests for the email report module."""

from datetime import datetime, timedelta

import pytest

from src.email_report import generate_report_html, EmailConfig


@pytest.fixture
def sample_items():
    """Create sample matched items for testing."""
    now = datetime.now()
    return [
        {
            "id": 1,
            "title": "Ergonomic Office Chair with Mesh Seat",
            "description": "High-quality office chair",
            "current_price": 45.00,
            "msrp": 199.99,
            "discount_pct": 77.5,
            "condition": "Like New",
            "auction_end": (now + timedelta(hours=12)).isoformat(),
            "pickup_location": "Columbus, OH 43215",
            "pickup_dates": "Jan 16-17, 9AM-5PM",
            "listing_url": "https://example.com/lot/12345",
            "source_site": "capital_city",
            "relevance_score": 92,
            "reasoning": "Excellent match - ergonomic office chair with mesh seat as specified",
            "confidence": "high",
            "is_new": True,
            "image_urls": ["https://example.com/images/chair.jpg"]
        },
        {
            "id": 2,
            "title": "Standing Desk Converter",
            "description": "Adjustable standing desk",
            "current_price": 85.00,
            "msrp": 299.99,
            "discount_pct": 71.7,
            "condition": "Good",
            "auction_end": (now + timedelta(days=3)).isoformat(),
            "pickup_location": "Westerville, OH 43081",
            "pickup_dates": "Jan 18-19, 10AM-4PM",
            "listing_url": "https://example.com/lot/12346",
            "source_site": "bidfta",
            "relevance_score": 78,
            "reasoning": "Good match for office furniture search",
            "confidence": "medium",
            "is_new": False,
            "image_urls": []
        }
    ]


def test_generate_report_html_basic(sample_items):
    """Test basic HTML report generation."""
    html = generate_report_html(sample_items)

    # Check that HTML is generated
    assert "<html>" in html
    assert "</html>" in html

    # Check that items are included
    assert "Ergonomic Office Chair" in html
    assert "Standing Desk Converter" in html

    # Check prices
    assert "$45.00" in html
    assert "$85.00" in html


def test_generate_report_html_badges(sample_items):
    """Test that badges are shown correctly."""
    html = generate_report_html(sample_items)

    # New badge for first item
    assert "badge-new" in html

    # High discount badge (>70%)
    assert "badge-discount" in html


def test_generate_report_html_ending_soon(sample_items):
    """Test ending soon badge for items within 48 hours."""
    html = generate_report_html(sample_items)

    # First item ends in 12 hours, should have ending soon badge
    assert "badge-ending" in html or "Ending Soon" in html


def test_generate_report_html_summary(sample_items):
    """Test summary statistics in report."""
    html = generate_report_html(sample_items)

    # Summary should show 2 total matches
    assert "2" in html  # Total matches


def test_generate_report_html_empty():
    """Test report with no items."""
    html = generate_report_html([])

    assert "No matches found today" in html


def test_generate_report_html_no_images():
    """Test handling of items without images."""
    items = [{
        "id": 1,
        "title": "Test Item",
        "current_price": 10.00,
        "listing_url": "https://example.com",
        "source_site": "test",
        "relevance_score": 80,
        "is_new": False,
        "image_urls": []
    }]

    html = generate_report_html(items)

    # Should show "No Image" placeholder
    assert "No Image" in html


def test_generate_report_html_missing_optional_fields():
    """Test handling of items with missing optional fields."""
    items = [{
        "id": 1,
        "title": "Minimal Item",
        "current_price": None,
        "listing_url": "https://example.com",
        "source_site": "test",
        "is_new": False,
        "image_urls": []
    }]

    # Should not raise exception
    html = generate_report_html(items)
    assert "Minimal Item" in html


def test_email_config_from_env(monkeypatch):
    """Test loading email config from environment."""
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "465")
    monkeypatch.setenv("EMAIL_USER", "test@test.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret123")
    monkeypatch.setenv("EMAIL_RECIPIENT", "recipient@test.com")

    config = EmailConfig.from_env()

    assert config.smtp_host == "smtp.test.com"
    assert config.smtp_port == 465
    assert config.username == "test@test.com"
    assert config.password == "secret123"
    assert config.recipient == "recipient@test.com"


def test_email_config_defaults(monkeypatch):
    """Test default values in email config."""
    # Clear environment variables
    for var in ["EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_USER", "EMAIL_PASSWORD", "EMAIL_RECIPIENT"]:
        monkeypatch.delenv(var, raising=False)

    config = EmailConfig.from_env()

    assert config.smtp_host == "smtp.gmail.com"
    assert config.smtp_port == 587
    assert config.username == ""


def test_generate_report_custom_date():
    """Test report with custom date."""
    items = []
    custom_date = datetime(2025, 6, 15, 10, 30, 0)

    html = generate_report_html(items, report_date=custom_date)

    assert "June 15, 2025" in html


def test_report_relevance_score_colors(sample_items):
    """Test that relevance scores use correct color classes."""
    html = generate_report_html(sample_items)

    # High score (92) should use green
    assert "score-high" in html

    # Medium score (78) should use yellow
    assert "score-medium" in html
