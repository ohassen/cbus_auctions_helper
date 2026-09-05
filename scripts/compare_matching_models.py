"""Compare relevance-matching quality between two OpenRouter models.

Runs the same SemanticMatcher prompt (src/matching.py) against a fixed set of
hand-built test cases modeled on the app's real active searches (searches.json)
and the matching rules already encoded in the prompt: true positives, lots/
bundles (should score 0), accessories/parts (should score below 70), and
clear category mismatches.

This makes REAL paid API calls to OpenRouter for each (model, test case) pair.
Cost is negligible (~2 dozen short text-only calls) but requires a working
OPEN_ROUTER_API_KEY.

Usage:
    export OPEN_ROUTER_API_KEY=sk-or-...
    python scripts/compare_matching_models.py
    python scripts/compare_matching_models.py --models google/gemini-3-flash-preview google/gemini-3.1-flash-lite
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import AuctionItem
from src.matching import SemanticMatcher

DEFAULT_MODELS = [
    "google/gemini-3-flash-preview",   # current production default
    "google/gemini-3.1-flash-lite",    # cheaper GA candidate
]

# (query, item, expected) — expected is what the prompt's own RULES section
# says the score *should* land as, not an external ground truth.
TEST_CASES = [
    ("dresser", AuctionItem(
        title="6-Drawer Wood Dresser with Mirror",
        description="Solid wood dresser, 6 drawers, matching mirror included.",
        current_price=85.0, condition="Used - Good",
    ), "match"),
    ("dresser", AuctionItem(
        title="Estate Lot: Dresser, 2 Lamps, Area Rug",
        description="Mixed household lot including a dresser, two table lamps, and a rug.",
        current_price=40.0, condition="Used",
    ), "no_match"),  # lot/bundle -> should score 0 per RULES
    ("projector", AuctionItem(
        title="Epson Home Cinema 1080p Projector",
        description="Home theater projector, 3400 lumens, includes remote.",
        current_price=150.0, condition="Like New",
    ), "match"),
    ("projector", AuctionItem(
        title="Projector Screen Mount Bracket",
        description="Ceiling mount bracket compatible with most projectors.",
        current_price=12.0, condition="New",
    ), "no_match"),  # accessory -> should score below 70
    ("garage opener", AuctionItem(
        title="Chamberlain Garage Door Opener 1/2 HP",
        description="Belt drive garage door opener with two remotes.",
        current_price=60.0, condition="Used - Good",
    ), "match"),
    ("garage opener", AuctionItem(
        title="Garage Door Opener Remote Control Only",
        description="Replacement remote, compatible with Chamberlain/LiftMaster.",
        current_price=8.0, condition="New",
    ), "no_match"),  # accessory/part -> below 70
    ("night stand", AuctionItem(
        title="White Nightstand with Drawer",
        description="Small bedside table, one drawer, one shelf.",
        current_price=20.0, condition="Used",
    ), "match"),
    ("night stand", AuctionItem(
        title="Nightstand Lamp - Touch Control",
        description="Small touch-activated bedside lamp.",
        current_price=15.0, condition="New",
    ), "no_match"),  # not a nightstand, just described as bedside
    ("bean bag", AuctionItem(
        title="Large Bean Bag Chair - Grey",
        description="Oversized bean bag chair, foam filled.",
        current_price=25.0, condition="Used - Good",
    ), "match"),
    ("bean bag", AuctionItem(
        title="Bean Bag Toss Game Set (Cornhole)",
        description="Cornhole boards with 8 bean bags.",
        current_price=30.0, condition="Used",
    ), "no_match"),  # "bean bag" mentioned incidentally, different product
    ("kettlebell", AuctionItem(
        title="25lb Cast Iron Kettlebell",
        description="Single kettlebell, cast iron, vinyl-coated base.",
        current_price=18.0, condition="Used - Good",
    ), "match"),
    ("kettlebell", AuctionItem(
        title="Assorted Home Gym Lot: Dumbbells, Kettlebell, Yoga Mat",
        description="Mixed fitness equipment lot.",
        current_price=45.0, condition="Used",
    ), "no_match"),  # lot/bundle -> should score 0
]


async def run_model(model: str, api_key: str) -> list[dict]:
    matcher = SemanticMatcher(api_key=api_key, model=model)
    results = []
    for query, item, expected in TEST_CASES:
        result = await matcher.evaluate_item(query, item)
        agrees = (result.is_match and expected == "match") or (
            not result.is_match and expected == "no_match"
        )
        results.append({
            "query": query,
            "title": item.title,
            "expected": expected,
            "score": result.relevance_score,
            "is_match": result.is_match,
            "confidence": result.confidence,
            "agrees_with_rules": agrees,
            "reasoning": result.reasoning,
        })
    return results


def print_report(model: str, results: list[dict]) -> None:
    agree_count = sum(r["agrees_with_rules"] for r in results)
    print(f"\n=== {model} ===")
    print(f"Agreement with prompt's own RULES: {agree_count}/{len(results)}")
    for r in results:
        flag = "OK " if r["agrees_with_rules"] else "MISMATCH"
        print(
            f"  [{flag}] '{r['query']}' vs \"{r['title']}\" -> "
            f"score={r['score']} match={r['is_match']} expected={r['expected']} "
            f"conf={r['confidence']}"
        )
        if not r["agrees_with_rules"]:
            print(f"           reasoning: {r['reasoning']}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args()

    api_key = os.getenv("OPEN_ROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPEN_ROUTER_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    all_results = {}
    for model in args.models:
        all_results[model] = await run_model(model, api_key)
        print_report(model, all_results[model])

    if len(args.models) == 2:
        m1, m2 = args.models
        same_verdict = sum(
            1 for a, b in zip(all_results[m1], all_results[m2])
            if a["is_match"] == b["is_match"]
        )
        print(f"\n=== Head-to-head ===")
        print(f"Match/no-match agreement between models: {same_verdict}/{len(TEST_CASES)}")


if __name__ == "__main__":
    asyncio.run(main())
