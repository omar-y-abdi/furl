"""Pure routing-policy mappings for the ContentRouter.

Extracted from ``content_router.py``. Everything here is a pure function of
its arguments — config thresholds + a content/strategy value — with no access
to router runtime state, the result cache, or thread-locals.

``CompressionStrategy`` lives here (rather than in ``content_router``) so the
strategy-mapping functions, whose dict keys/values ARE ``CompressionStrategy``
members, can be defined without importing back from ``content_router`` — that
would form an import cycle. ``content_router`` re-exports the enum, so existing
``from ...content_router import CompressionStrategy`` imports and the package
lazy-export both keep resolving the single canonical object.

Dependency-light by design: imports only ``ContentType`` /
``DetectionResult`` from ``content_detector``; never imports
``content_router``. The config parameters are therefore typed as narrow
PROTOCOLS of exactly the fields each policy function reads (TYPE-3) —
``ContentRouterConfig`` satisfies them structurally without this module
importing it.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from .content_detector import ContentType, DetectionResult


class CompressionStrategy(Enum):
    """Available compression strategies."""

    SMART_CRUSHER = "smart_crusher"
    SEARCH = "search"
    LOG = "log"
    TEXT = "text"
    DIFF = "diff"
    # Opt-in AST code compression (Engine P2-12, `enable_code_aware`).
    CODE_AWARE = "code_aware"
    MIXED = "mixed"
    PASSTHROUGH = "passthrough"
    # Reversible last-resort offload to the CCR store (ContentRouter fallback).
    CCR_OFFLOAD = "ccr_offload"


class StrategyPolicyConfig(Protocol):
    """The config fields the strategy-mapping policy reads."""

    fallback_strategy: CompressionStrategy
    enable_code_aware: bool


class RatioPolicyConfig(Protocol):
    """The config fields the adaptive-ratio policy reads."""

    min_ratio_relaxed: float
    min_ratio_aggressive: float


def strategy_from_detection(
    config: StrategyPolicyConfig, detection: DetectionResult
) -> CompressionStrategy:
    """Get strategy from content detection result.

    Args:
        config: ``ContentRouterConfig`` (or any object with the
            ``StrategyPolicyConfig`` fields).
        detection: Result from detect_content_type.

    Returns:
        Selected strategy.
    """
    mapping = {
        ContentType.SOURCE_CODE: _source_code_strategy(config),
        ContentType.JSON_ARRAY: CompressionStrategy.SMART_CRUSHER,
        ContentType.SEARCH_RESULTS: CompressionStrategy.SEARCH,
        ContentType.BUILD_OUTPUT: CompressionStrategy.LOG,
        ContentType.GIT_DIFF: CompressionStrategy.DIFF,
        ContentType.PLAIN_TEXT: CompressionStrategy.TEXT,
    }
    return mapping.get(detection.content_type, config.fallback_strategy)


def _source_code_strategy(config: StrategyPolicyConfig) -> CompressionStrategy:
    """SOURCE_CODE routing: PASSTHROUGH by default — code ships unmangled,
    exactly the behavior the retired AST/ML code compressors left behind.
    The opt-in CodeAwareCompressor (``enable_code_aware=True``, Engine
    P2-12) claims the arm instead; its dispatch arm applies the
    ``lossless_only`` gate."""
    if config.enable_code_aware:
        return CompressionStrategy.CODE_AWARE
    return CompressionStrategy.PASSTHROUGH


def strategy_from_detection_type(
    config: StrategyPolicyConfig, content_type: ContentType
) -> CompressionStrategy:
    """Get strategy from ContentType enum."""
    mapping = {
        ContentType.SOURCE_CODE: _source_code_strategy(config),
        ContentType.JSON_ARRAY: CompressionStrategy.SMART_CRUSHER,
        ContentType.SEARCH_RESULTS: CompressionStrategy.SEARCH,
        ContentType.BUILD_OUTPUT: CompressionStrategy.LOG,
        ContentType.GIT_DIFF: CompressionStrategy.DIFF,
        ContentType.PLAIN_TEXT: CompressionStrategy.TEXT,
    }
    return mapping.get(content_type, config.fallback_strategy)


def content_type_from_strategy(strategy: CompressionStrategy) -> ContentType:
    """Get ContentType from strategy."""
    mapping = {
        CompressionStrategy.SMART_CRUSHER: ContentType.JSON_ARRAY,
        CompressionStrategy.SEARCH: ContentType.SEARCH_RESULTS,
        CompressionStrategy.LOG: ContentType.BUILD_OUTPUT,
        CompressionStrategy.DIFF: ContentType.GIT_DIFF,
        CompressionStrategy.CODE_AWARE: ContentType.SOURCE_CODE,
        CompressionStrategy.TEXT: ContentType.PLAIN_TEXT,
        CompressionStrategy.PASSTHROUGH: ContentType.PLAIN_TEXT,
        CompressionStrategy.CCR_OFFLOAD: ContentType.PLAIN_TEXT,
    }
    return mapping.get(strategy, ContentType.PLAIN_TEXT)


def adaptive_min_ratio(config: RatioPolicyConfig, context_pressure: float) -> float:
    """Compression-acceptance threshold scaled by context pressure.

    A compression is accepted when ``ratio < min_ratio`` (lower ratio =
    more aggressive). A HIGHER ``min_ratio`` accepts more compressions.
    At low pressure use the relaxed (stricter, lower) threshold; at high
    pressure use the aggressive (permissive, higher) threshold, so the
    agent accepts marginal compressions exactly when context is tightest.
    Monotone non-decreasing in ``context_pressure``; clamped to
    ``[relaxed, aggressive]``.
    """
    relaxed: float = config.min_ratio_relaxed
    aggressive: float = config.min_ratio_aggressive
    min_ratio = relaxed + (aggressive - relaxed) * context_pressure
    return max(relaxed, min(aggressive, min_ratio))
