"""Option-aware, collision-guarded result-cache keys (COR-18).

The two-tier result cache used to key on ``hash(content)`` alone, with two
consequences:

(a) per-request options were DEFEATED on hits — a Tier-1 skip hit served the
    original even under ``force_kompress=True``, and a Tier-2 hit served a
    result computed under a different ``target_ratio`` / ``kompress_model`` /
    bias, silently ignoring the public per-call API options whenever the same
    bytes recurred within the TTL;
(b) the bare 64-bit SipHash key was served with no content-equality
    verification, so a hash collision substituted another message's
    compressed bytes (CrossMessageDeduper verifies ``first.content ==
    content``; the router cache did not).

``_result_cache_key(content, runtime, bias)`` fixes both: the key is
``(hash(content), len(content), runtime, round(bias, 3))``, so dict key
EQUALITY — not just the 64-bit hash — verifies content length and the exact
per-request option set before any hit is served. ``context`` is deliberately
NOT in the key (it changes every turn in agent traffic; ``min_ratio`` and CCR
backing are re-checked per hit) — see the helper's docstring.
"""

from __future__ import annotations

from headroom.tokenizer import Tokenizer
from headroom.tokenizers import EstimatingTokenCounter
from headroom.transforms.content_router import (
    _DEFAULT_RUNTIME,
    ContentRouter,
    ContentRouterConfig,
    RouterRuntime,
    _result_cache_key,
)


def _make_tokenizer() -> Tokenizer:
    return Tokenizer(EstimatingTokenCounter())


def _routable_tool_content() -> str:
    """Deterministic tool output that clears every pre-cache protection gate
    (same fixture family as test_content_router_cache_lookup_paths)."""
    return " ".join(
        f"Line {i}: the nightly report recorded steady throughput and "
        f"nominal latency across shard {i % 5} with no anomalies noted."
        for i in range(12)
    )


def _tool_message(content: str) -> dict:
    return {"role": "tool", "content": content, "tool_call_id": "call_opts"}


def _default_key(content: str):
    return _result_cache_key(content, _DEFAULT_RUNTIME, 1.0)


class TestKeyStructure:
    def test_key_carries_length_guard_and_options(self):
        """Characterization pin on the key tuple: content hash + LENGTH GUARD
        + runtime + rounded bias. The length in the key is the collision
        guard — dict key equality rejects a same-hash/different-length
        collision as a plain miss instead of serving foreign bytes."""
        content = "some tool output payload"
        runtime = RouterRuntime(target_ratio=0.4)
        assert _result_cache_key(content, runtime, 1.25) == (
            hash(content),
            len(content),
            runtime,
            1.25,
        )

    def test_distinct_runtimes_produce_distinct_keys(self):
        content = _routable_tool_content()
        assert _default_key(content) != _result_cache_key(
            content, RouterRuntime(force_kompress=True), 1.0
        )
        assert _default_key(content) != _result_cache_key(
            content, RouterRuntime(kompress_model="tiny"), 1.0
        )
        assert _default_key(content) != _result_cache_key(
            content, RouterRuntime(target_ratio=0.3), 1.0
        )

    def test_near_equal_bias_rounds_to_same_key(self):
        """Bias rides rounded to 3 decimals so float jitter from multiplicative
        hook biases doesn't fragment the cache."""
        content = _routable_tool_content()
        rt = _DEFAULT_RUNTIME
        assert _result_cache_key(content, rt, 1.0001) == _result_cache_key(content, rt, 1.0004)
        assert _result_cache_key(content, rt, 1.0) != _result_cache_key(content, rt, 1.5)


class TestOptionAwareServing:
    """End-to-end: entries created under one option set are never served under
    another. Kompress is disabled in these routers so the forced-strategy
    recompute is a deterministic passthrough (no ML model in the loop)."""

    def _router(self) -> ContentRouter:
        return ContentRouter(ContentRouterConfig(enable_kompress=False))

    def test_tier2_hit_not_served_under_force_kompress(self):
        """The exact COR-18(a) scenario: a cached default-options compression
        must NOT satisfy a ``force_kompress=True`` request."""
        content = _routable_tool_content()
        router = self._router()
        router._cache.put(_default_key(content), "DEFAULT-OPTIONS-PAYLOAD", 0.3, "log")

        result = router.apply([_tool_message(content)], _make_tokenizer(), force_kompress=True)

        # The default-options payload was withheld; the forced request
        # recomputed (kompress disabled → passthrough → original served).
        assert result.messages[0]["content"] == content
        assert "DEFAULT-OPTIONS-PAYLOAD" not in result.messages[0]["content"]

    def test_tier1_skip_not_honored_under_force_kompress(self):
        """A Tier-1 'won't compress' verdict from the default option set must
        not short-circuit a forced request — the forced key misses."""
        content = _routable_tool_content()
        router = self._router()
        router._cache.mark_skip(_default_key(content))
        before = dict(router._cache.stats)

        router.apply([_tool_message(content)], _make_tokenizer(), force_kompress=True)

        after = dict(router._cache.stats)
        # No skip hit at the forced key — the request went to recompute.
        assert after["cache_skip_hits"] - before["cache_skip_hits"] == 0
        assert after["cache_misses"] - before["cache_misses"] >= 1

    def test_tier2_hit_not_served_under_different_hook_bias(self):
        content = _routable_tool_content()
        router = self._router()
        router._cache.put(_default_key(content), "BIAS-1.0-PAYLOAD", 0.3, "log")

        result = router.apply([_tool_message(content)], _make_tokenizer(), biases={0: 2.0})

        assert result.messages[0]["content"] == content
        assert "BIAS-1.0-PAYLOAD" not in result.messages[0]["content"]

    def test_same_options_still_hit(self):
        """Regression guard: the richer key must not break the normal same-
        options hit path the cache exists for."""
        content = _routable_tool_content()
        router = self._router()
        router._cache.put(_default_key(content), "SAME-OPTIONS-PAYLOAD", 0.3, "log")

        result = router.apply([_tool_message(content)], _make_tokenizer())

        assert result.messages[0]["content"] == "SAME-OPTIONS-PAYLOAD"
        assert "router:log:0.30" in result.transforms_applied
