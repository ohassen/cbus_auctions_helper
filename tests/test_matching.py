"""Tests for semantic matching module."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime

from src.matching import SemanticMatcher, MatchResult
from src.database import AuctionItem


@pytest.fixture
def sample_item():
    """Sample auction item for matching tests."""
    return AuctionItem(
        id=1,
        search_id="search-001",
        source_site="capital_city",
        external_id="12345",
        title="KitchenAid Artisan Bread Maker Machine",
        description="Automatic bread maker with 12 settings",
        current_price=45.00,
        condition="Like New",
        listing_url="https://example.com/lot/12345",
        image_urls=[]
    )


def _make_mock_client(response_text: str):
    """Build a mock Anthropic client that returns a specific response."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = response_text

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


class TestSemanticMatcherInit:
    """Tests for SemanticMatcher initialization."""

    def test_init_with_explicit_key(self):
        """Can construct with explicit API key."""
        matcher = SemanticMatcher(api_key="sk-ant-test-key")
        assert matcher.api_key == "sk-ant-test-key"

    def test_init_raises_without_key(self, monkeypatch):
        """Raises ValueError when no API key available."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not set"):
            SemanticMatcher()

    def test_init_reads_env_var(self, monkeypatch):
        """Reads API key from environment variable."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-key")
        matcher = SemanticMatcher()
        assert matcher.api_key == "sk-ant-env-key"

    def test_default_threshold(self):
        """Default relevance threshold is 70."""
        matcher = SemanticMatcher(api_key="sk-ant-test")
        assert matcher.relevance_threshold == 70

    def test_custom_threshold(self):
        """Custom threshold is respected."""
        matcher = SemanticMatcher(api_key="sk-ant-test", relevance_threshold=80)
        assert matcher.relevance_threshold == 80


class TestValidateApiKey:
    """Tests for the API key validation method."""

    @pytest.mark.asyncio
    async def test_validate_returns_true_on_success(self):
        """validate_api_key returns True when API call succeeds."""
        matcher = SemanticMatcher(api_key="sk-ant-valid-key")
        matcher.client = _make_mock_client("hi")

        result = await matcher.validate_api_key()
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_returns_false_on_auth_error(self):
        """validate_api_key returns False when API raises an exception."""
        matcher = SemanticMatcher(api_key="sk-ant-expired-key")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception(
            "401 Unauthorized: Invalid API key"
        )
        matcher.client = mock_client

        result = await matcher.validate_api_key()
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_returns_false_on_any_exception(self):
        """validate_api_key catches all exceptions and returns False."""
        matcher = SemanticMatcher(api_key="sk-ant-test")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = ConnectionError("Network unreachable")
        matcher.client = mock_client

        result = await matcher.validate_api_key()
        assert result is False


class TestEvaluateItem:
    """Tests for the evaluate_item method."""

    @pytest.mark.asyncio
    async def test_high_score_is_a_match(self, sample_item):
        """Items with score >= threshold are matches."""
        matcher = SemanticMatcher(api_key="sk-ant-test", relevance_threshold=70)
        matcher.client = _make_mock_client(
            '{"relevance_score": 90, "reasoning": "Perfect bread maker match.", "confidence": "high"}'
        )

        result = await matcher.evaluate_item("bread maker", sample_item)

        assert result.is_match is True
        assert result.relevance_score == 90
        assert result.confidence == "high"

    @pytest.mark.asyncio
    async def test_low_score_is_not_a_match(self, sample_item):
        """Items with score < threshold are not matches."""
        matcher = SemanticMatcher(api_key="sk-ant-test", relevance_threshold=70)
        matcher.client = _make_mock_client(
            '{"relevance_score": 30, "reasoning": "Not relevant.", "confidence": "high"}'
        )

        result = await matcher.evaluate_item("bread maker", sample_item)

        assert result.is_match is False
        assert result.relevance_score == 30

    @pytest.mark.asyncio
    async def test_score_at_threshold_is_a_match(self, sample_item):
        """Items with score exactly at threshold ARE matches."""
        matcher = SemanticMatcher(api_key="sk-ant-test", relevance_threshold=70)
        matcher.client = _make_mock_client(
            '{"relevance_score": 70, "reasoning": "Borderline match.", "confidence": "medium"}'
        )

        result = await matcher.evaluate_item("bread maker", sample_item)

        assert result.is_match is True

    @pytest.mark.asyncio
    async def test_api_failure_returns_zero_score_with_error_reasoning(self, sample_item):
        """When API fails, returns score=0 with error reasoning (not a match).

        The reasoning field starts with 'Evaluation failed:' so callers can
        detect API errors vs legitimate low scores.
        """
        matcher = SemanticMatcher(api_key="sk-ant-expired")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("401 Unauthorized")
        matcher.client = mock_client

        result = await matcher.evaluate_item("bread maker", sample_item)

        assert result.is_match is False
        assert result.relevance_score == 0
        assert result.reasoning.startswith("Evaluation failed:")

    @pytest.mark.asyncio
    async def test_malformed_json_returns_zero_score(self, sample_item):
        """When API returns malformed JSON, returns score=0 with error reasoning."""
        matcher = SemanticMatcher(api_key="sk-ant-test")
        matcher.client = _make_mock_client("not valid json at all")

        result = await matcher.evaluate_item("bread maker", sample_item)

        assert result.is_match is False
        assert result.relevance_score == 0
        assert result.reasoning.startswith("Evaluation failed:")

    @pytest.mark.asyncio
    async def test_json_in_markdown_code_block_is_parsed(self, sample_item):
        """Handles JSON wrapped in markdown code fences."""
        matcher = SemanticMatcher(api_key="sk-ant-test")
        matcher.client = _make_mock_client(
            '```json\n{"relevance_score": 85, "reasoning": "Match.", "confidence": "high"}\n```'
        )

        result = await matcher.evaluate_item("bread maker", sample_item)

        assert result.relevance_score == 85
        assert result.is_match is True


class TestApiErrorDetection:
    """Tests for detecting API errors vs legitimate zero scores in run_semantic_matching."""

    @pytest.mark.asyncio
    async def test_api_error_is_counted_not_swallowed(self, sample_item):
        """API errors increment the error count returned from run_semantic_matching."""
        import tempfile
        from src.database import Database, MatchMetadata
        from src.main import run_semantic_matching
        from src.database import Search
        from datetime import date

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        async with Database(db_path) as db:
            # Insert a sample item seen today
            item_id = await db.upsert_item(sample_item)

            matcher = SemanticMatcher(api_key="sk-ant-expired")
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = Exception("401 Unauthorized")
            matcher.client = mock_client

            search = Search(
                id="search-001",
                query="bread maker",
                active=True,
                created_at=datetime.now()
            )

            matches, api_errors = await run_semantic_matching(db, matcher, [search])

            # Should report the error, not silently return 0
            assert matches == 0
            assert api_errors == 1

        import os
        os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_successful_match_zero_errors(self, sample_item):
        """Successful matches produce 0 errors."""
        import tempfile
        from src.database import Database
        from src.main import run_semantic_matching
        from src.database import Search

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        async with Database(db_path) as db:
            item_id = await db.upsert_item(sample_item)

            matcher = SemanticMatcher(api_key="sk-ant-valid")
            matcher.client = _make_mock_client(
                '{"relevance_score": 85, "reasoning": "Good match.", "confidence": "high"}'
            )

            search = Search(
                id="search-001",
                query="bread maker",
                active=True,
                created_at=datetime.now()
            )

            matches, api_errors = await run_semantic_matching(db, matcher, [search])

            assert matches == 1
            assert api_errors == 0

        import os
        os.unlink(db_path)


class TestKeyTermExtraction:
    """Tests for key term extraction with and without API."""

    def test_fallback_extracts_last_word(self):
        """Fallback extracts the last non-stop word."""
        from src.scrapers.capital_city import _fallback_key_term_extraction

        assert _fallback_key_term_extraction("office chair") == "chair"
        assert _fallback_key_term_extraction("gooseneck kettle") == "kettle"

    def test_fallback_skips_stop_words(self):
        """Fallback ignores common stop/modifier words."""
        from src.scrapers.capital_city import _fallback_key_term_extraction

        # "manual" is in stop_words, so "manual coffee grinder" → "grinder"
        assert _fallback_key_term_extraction("manual coffee grinder") == "grinder"

    def test_fallback_bread_maker_returns_maker(self):
        """'bread maker' fallback returns 'maker' - note this is a known weak fallback.

        The Claude-powered version would return 'bread maker' or 'maker' more intelligently.
        This test documents the current behavior so regressions are visible.
        """
        from src.scrapers.capital_city import _fallback_key_term_extraction

        result = _fallback_key_term_extraction("bread maker")
        # 'maker' is what the fallback returns - this may not be ideal
        assert result == "maker"

    def test_extract_key_term_uses_cache(self, monkeypatch):
        """Key term cache prevents redundant API calls."""
        from src.scrapers import capital_city
        from src.scrapers.capital_city import extract_key_term, _KEY_TERM_CACHE

        # Pre-populate the cache
        _KEY_TERM_CACHE["drone"] = "drone"

        # Should return cached value without calling API
        result = extract_key_term("drone")
        assert result == "drone"

    def test_extract_key_term_falls_back_without_api_key(self, monkeypatch):
        """Falls back to simple extraction when ANTHROPIC_API_KEY is not set."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        # Clear cache to force fresh extraction
        from src.scrapers import capital_city
        capital_city._KEY_TERM_CACHE.clear()

        from src.scrapers.capital_city import extract_key_term
        result = extract_key_term("gooseneck kettle")
        assert result == "kettle"
