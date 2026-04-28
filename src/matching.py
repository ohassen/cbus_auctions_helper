"""Claude semantic matching for auction items via OpenRouter."""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from .database import AuctionItem, MatchMetadata

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result from semantic matching."""
    relevance_score: int
    reasoning: str
    confidence: str
    is_match: bool


@dataclass
class PriceLookupResult:
    """Result from MSRP lookup."""
    msrp: Optional[float]
    source: str
    confidence: str


class SemanticMatcher:
    """Claude-powered semantic matching for auction items via OpenRouter."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "google/gemma-4-26b-a4b-it:free",
        relevance_threshold: int = 70
    ):
        self.api_key = api_key or os.getenv("OPEN_ROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPEN_ROUTER_API_KEY not set")

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )
        self.model = model
        self.relevance_threshold = relevance_threshold

    async def validate_api_key(self) -> tuple[bool, str]:
        """Validate the API key by making a minimal test call.

        Returns (True, "") if the key is valid, (False, error_message) otherwise.
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=5,
                    messages=[{"role": "user", "content": "hi"}]
                )
            )
            logger.info("OPEN_ROUTER_API_KEY validated successfully")
            return True, ""
        except Exception as e:
            error_detail = str(e)
            logger.error(f"OPEN_ROUTER_API_KEY validation failed: {error_detail}")
            return False, error_detail

    def _build_match_prompt(self, query: str, item: AuctionItem) -> str:
        """Build the matching prompt."""
        # Format price properly
        price_str = f"${item.current_price:.2f}" if item.current_price is not None else "Unknown"

        return f"""You are evaluating auction items for relevance to a buyer's search.

SEARCH QUERY: {query}

ITEM DETAILS:
- Title: {item.title}
- Description: {item.description or 'No description available'}
- Condition: {item.condition or 'Unknown'}
- Current Price: {price_str}

QUESTION: Is this auction item specifically and primarily "{query}"?

SCORING GUIDE:
- 90-100: Item clearly IS {query}
- 70-89: Item is {query}, but with some uncertainty (vague title, missing description)
- 50-69: Related to {query} — compatible with, an accessory for, or a category that could include one
- 0-49: Not {query} — different product, only mentions {query} incidentally

RULES:
- Lots, bundles, or collections of multiple items score 0, even if {query} may be among them
- Accessories, cases, parts, or peripherals for {query} score below 70
- If uncertain, score conservatively (below 70)

Respond in this EXACT JSON format:
{{
    "relevance_score": <0-100 integer>,
    "reasoning": "<2-3 sentences explaining your score>",
    "confidence": "<high|medium|low>"
}}

Respond with ONLY the JSON, no other text."""

    async def evaluate_item(
        self,
        query: str,
        item: AuctionItem
    ) -> MatchResult:
        """Evaluate if an item matches the search query using text only."""
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                # Call Claude via OpenRouter (synchronous SDK, but we'll run in executor)
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        max_tokens=500,
                        messages=[{
                            "role": "user",
                            "content": self._build_match_prompt(query, item)
                        }]
                    )
                )

                # Parse response
                response_text = response.choices[0].message.content.strip()

                # Extract JSON (handle potential markdown code blocks)
                if "```" in response_text:
                    import re
                    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
                    if json_match:
                        response_text = json_match.group(1)

                import json
                result = json.loads(response_text)

                score = int(result.get("relevance_score", 0))
                reasoning = result.get("reasoning", "No reasoning provided")
                confidence = result.get("confidence", "low")

                return MatchResult(
                    relevance_score=score,
                    reasoning=reasoning,
                    confidence=confidence,
                    is_match=score >= self.relevance_threshold
                )

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_seconds = 2 ** (attempt + 1)  # 2s then 4s
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries} failed for "
                        f"'{item.title[:50]}': {e}. Retrying in {wait_seconds}s..."
                    )
                    await asyncio.sleep(wait_seconds)
                else:
                    logger.error(
                        f"All {max_retries} attempts failed for '{item.title[:50]}': {e}"
                    )

        return MatchResult(
            relevance_score=0,
            reasoning=f"Evaluation failed: {str(last_error)}",
            confidence="low",
            is_match=False
        )

    async def lookup_msrp(self, item: AuctionItem) -> PriceLookupResult:
        """Look up MSRP for an item using Claude's web search."""

        prompt = f"""I need to find the retail/MSRP price for this product:

Title: {item.title}
Description: {item.description[:500] if item.description else 'No description'}

Please search for the retail price of this item or a very similar product.
Provide your response in this EXACT JSON format:
{{
    "msrp": <price as number or null if not found>,
    "source": "<where you found this price or 'estimated' if approximated>",
    "confidence": "<high|medium|low>"
}}

If you cannot find an exact match, provide an estimate based on similar products.
If you truly cannot determine a price, set msrp to null.

Respond with ONLY the JSON, no other text."""

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}]
                )
            )

            response_text = response.choices[0].message.content.strip()

            # Extract JSON
            if "```" in response_text:
                import re
                json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(1)

            import json
            result = json.loads(response_text)

            msrp = result.get("msrp")
            if msrp is not None:
                msrp = float(msrp)

            return PriceLookupResult(
                msrp=msrp,
                source=result.get("source", "unknown"),
                confidence=result.get("confidence", "low")
            )

        except Exception as e:
            logger.error(f"Error looking up MSRP for {item.title[:50]}: {e}")
            return PriceLookupResult(
                msrp=None,
                source=f"Error: {str(e)}",
                confidence="low"
            )


async def process_items_batch(
    matcher: SemanticMatcher,
    items: list[AuctionItem],
    query: str,
    batch_size: int = 5
) -> list[tuple[AuctionItem, MatchResult]]:
    """Process items in batches with rate limiting."""

    results = []
    total = len(items)

    for i in range(0, total, batch_size):
        batch = items[i:i + batch_size]
        logger.info(f"Processing batch {i // batch_size + 1}/{(total + batch_size - 1) // batch_size}")

        # Process batch concurrently
        tasks = [matcher.evaluate_item(query, item) for item in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for item, result in zip(batch, batch_results):
            if isinstance(result, Exception):
                logger.error(f"Error processing {item.title[:50]}: {result}")
                result = MatchResult(
                    relevance_score=0,
                    reasoning=f"Error: {str(result)}",
                    confidence="low",
                    is_match=False
                )
            results.append((item, result))

        # Rate limit between batches
        if i + batch_size < total:
            await asyncio.sleep(1)

    return results
