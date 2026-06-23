"""Relevance scoring module for Headroom SDK.

This module provides a unified interface for computing item relevance against
query contexts. All scorers implement the RelevanceScorer protocol:

    relevance(item, context) -> RelevanceScore

Available scorers:

1. BM25Scorer (zero dependencies)
   - Fast keyword matching
   - Good for exact UUIDs, IDs, specific terms
   - May miss semantic matches ("errors" won't match "failed")

The semantic/embedding scorers were retired with the public SDK surface; the
live compression core scores items via the Rust HybridScorer, and only
``BM25Scorer`` remains as the Python keyword scorer (used by the CCR store's
search path).

Example usage:
    from headroom.relevance import BM25Scorer, create_scorer

    scorer = create_scorer("bm25")  # or BM25Scorer()

    # Score items
    items = [
        '{"id": "123", "name": "Alice"}',
        '{"id": "456", "name": "Bob"}',
    ]
    scores = scorer.score_batch(items, "find user 123")
    # scores[0].score > scores[1].score
"""

from typing import Any

from .base import RelevanceScore, RelevanceScorer
from .bm25 import BM25Scorer

__all__ = [
    # Base types
    "RelevanceScore",
    "RelevanceScorer",
    # Scorers
    "BM25Scorer",
    # Factory function
    "create_scorer",
]


def create_scorer(
    tier: str = "bm25",
    **kwargs: Any,
) -> RelevanceScorer:
    """Factory function to create a relevance scorer.

    Args:
        tier: Scorer tier to create. Only ``"bm25"`` is available in the
            Python surface (zero deps, fast keyword scoring).
        **kwargs: Additional arguments passed to scorer constructor.

    Returns:
        RelevanceScorer instance.

    Raises:
        ValueError: If tier is unknown.
    """
    tier = tier.lower()

    if tier == "bm25":
        return BM25Scorer(**kwargs)

    valid_tiers = ["bm25"]
    raise ValueError(f"Unknown scorer tier: {tier}. Valid tiers: {valid_tiers}")
