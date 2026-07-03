"""COR-21 / PERF-11 / ENGINE P1-9 regression pins for ``CompressionCache``.

The old header claimed "all access happens on the main thread … lock-free
design … must be preserved", but the pipeline is a process-wide singleton
(``compress._get_pipeline``) and the MCP server runs ``compress()`` on an
executor thread — concurrent ``apply()`` calls share ONE cache. These tests
pin the hardened contract:

* **COR-21 crash**: two threads hitting the same expired key both passed the
  non-None check and both ``del`` → ``KeyError`` on the hot path (same shape
  in ``is_skipped``). Pinned deterministically (an injected dict simulates
  the eviction landing inside the lookup window) and probabilistically
  (barrier-synchronized hammer threads).
* **PERF-11 leak**: eviction was lazy per-key only, so unique content — the
  common case for tool outputs, inserted once and never looked up again —
  leaked forever in a long-lived MCP server. Pinned: an insertion-driven
  sweep reclaims expired entries in both tiers with NO lookups on the dead
  keys, and a FIFO per-tier cap bounds bursts inside one TTL window.
* **ENGINE P1-9 clock**: expiry math must use ``time.monotonic()`` — a
  wall-clock (NTP) step under ``time.time()`` could spuriously expire or
  immortalize entries.
* **COR-21 counters**: metric counters formerly raced benignly (lost ``+=``
  increments); under the lock they are exact, which ``stats`` now pins.
"""

from __future__ import annotations

import threading

import furl_ctx.transforms.router_cache as router_cache_module
from furl_ctx.transforms.router_cache import (
    _SWEEP_EVERY_N_INSERTIONS,
    CompressionCache,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hammer(worker, n_threads: int = 8) -> list[BaseException]:
    """Run *worker* on *n_threads* barrier-synchronized threads.

    Returns every exception any thread raised (empty list == clean run).
    """
    barrier = threading.Barrier(n_threads)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait()
            worker()
        except BaseException as exc:  # noqa: BLE001 - the assertion surface
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


class _EvictingResultsDict(dict):
    """Simulates the COR-21 interleave deterministically: another thread
    evicts the key inside the window between the lookup's non-None check and
    its eviction. ``del`` there raises ``KeyError``; ``pop(key, None)`` is a
    no-op."""

    def get(self, key, default=None):
        value = super().get(key, default)
        if value is not None:
            super().pop(key, None)  # concurrent eviction lands HERE
        return value


# ---------------------------------------------------------------------------
# COR-21: expired-key eviction must never raise
# ---------------------------------------------------------------------------


def test_expired_get_tolerates_concurrent_eviction_deterministic() -> None:
    """The exact COR-21 crash shape, deterministically: the entry vanishes
    between the expiry check and the eviction. Old code: ``KeyError``."""
    cache = CompressionCache(ttl_seconds=0)  # every entry is instantly expired
    racing: _EvictingResultsDict = _EvictingResultsDict()
    cache._results = racing
    cache.put("k", "payload", 0.5, "log")

    assert cache.get("k") is None  # expired + concurrently evicted: no crash


def test_expired_is_skipped_tolerates_concurrent_eviction_deterministic() -> None:
    """Same shape on the Tier-1 skip set."""
    cache = CompressionCache(ttl_seconds=0)
    racing: _EvictingResultsDict = _EvictingResultsDict()
    cache._skip = racing
    cache.mark_skip("s")

    assert cache.is_skipped("s") is False  # expired + evicted: no crash


def test_concurrent_expired_result_lookups_never_raise() -> None:
    """Hammer the Tier-2 expiry path from 8 threads on ONE shared key.

    ``ttl_seconds=0`` makes every entry instantly expired, so every ``get``
    after a ``put`` takes the eviction branch — the branch that crashed with
    ``del`` under the old lock-free design.
    """
    cache = CompressionCache(ttl_seconds=0)

    def worker() -> None:
        for _ in range(400):
            cache.put("shared", "payload", 0.5, "log")
            cache.get("shared")

    assert _hammer(worker) == []


def test_concurrent_expired_skip_lookups_never_raise() -> None:
    """Same hammer on the Tier-1 skip set (``is_skipped`` eviction branch)."""
    cache = CompressionCache(ttl_seconds=0)

    def worker() -> None:
        for _ in range(400):
            cache.mark_skip("shared")
            cache.is_skipped("shared")

    assert _hammer(worker) == []


def test_concurrent_mixed_operations_never_raise() -> None:
    """Full public surface under contention: put/get/mark_skip/is_skipped/
    move_to_skip/invalidate/stats/clear racing on overlapping keys."""
    cache = CompressionCache(ttl_seconds=0)

    def worker() -> None:
        for i in range(200):
            key = ("k", i % 7)
            cache.put(key, "payload", 0.5, "log")
            cache.get(key)
            cache.mark_skip(key)
            cache.is_skipped(key)
            cache.move_to_skip(key)
            cache.invalidate(key)
            _ = cache.stats
            if i % 50 == 49:
                cache.clear()

    assert _hammer(worker) == []


# ---------------------------------------------------------------------------
# ENGINE P1-9: expiry rides the monotonic clock, not the wall clock
# ---------------------------------------------------------------------------


def test_ttl_expiry_uses_monotonic_clock(monkeypatch) -> None:
    """TTL math must consult ``time.monotonic()`` and ignore ``time.time()``.

    The wall clock is patched to an absurd constant: under the old
    ``time.time()`` implementation both the stored and the checked timestamp
    read that constant, the age is always 0, and the entry never expires —
    so the expiry assertions below fail.
    """
    mono = {"now": 100.0}
    monkeypatch.setattr(router_cache_module.time, "monotonic", lambda: mono["now"])
    monkeypatch.setattr(router_cache_module.time, "time", lambda: 9e12)

    cache = CompressionCache(ttl_seconds=10)
    cache.put("k", "payload", 0.5, "log")
    cache.mark_skip("s")

    mono["now"] = 109.0  # age 9 < ttl 10: live
    assert cache.get("k") == ("payload", 0.5, "log")
    assert cache.is_skipped("s") is True

    mono["now"] = 110.0  # age == ttl: expired (strict `< ttl` liveness)
    assert cache.get("k") is None
    assert cache.is_skipped("s") is False
    assert cache.stats["cache_evictions"] == 2


# ---------------------------------------------------------------------------
# PERF-11: insertion-driven sweep reclaims unique content with no lookups
# ---------------------------------------------------------------------------


def test_sweep_reclaims_expired_entries_without_lookups(monkeypatch) -> None:
    """The MCP leak shape: unique content is inserted once and never looked
    up again, so lazy per-key eviction never fires. Insertions alone must
    reclaim the dead entries once the sweep interval elapses."""
    mono = {"now": 1_000.0}
    monkeypatch.setattr(router_cache_module.time, "monotonic", lambda: mono["now"])

    cache = CompressionCache(ttl_seconds=10)
    for i in range(100):
        cache.put(("result", i), "payload", 0.5, "log")
        cache.mark_skip(("skip", i))
    assert cache.size == 100
    assert cache.skip_size == 100

    mono["now"] = 2_000.0  # everything above is now long expired

    # Fresh insertions only — the dead keys are NEVER passed to get() or
    # is_skipped(), so only the sweep can reclaim them.
    fresh_puts = _SWEEP_EVERY_N_INSERTIONS + 1
    for i in range(fresh_puts):
        cache.put(("fresh", i), "payload", 0.5, "log")

    # All 100 dead results and all 100 dead skips are gone; only live fresh
    # entries remain. Without the sweep, size would be 100 + fresh_puts.
    assert cache.size <= fresh_puts
    assert cache.skip_size == 0
    assert cache.stats["cache_evictions"] >= 200


# ---------------------------------------------------------------------------
# PERF-11: FIFO per-tier cap bounds bursts inside one TTL window
# ---------------------------------------------------------------------------


def test_results_fifo_cap_evicts_oldest_first() -> None:
    cache = CompressionCache(ttl_seconds=3600, max_entries=32)
    for i in range(40):
        cache.put(("k", i), "payload", 0.5, "log")

    assert cache.size == 32
    assert cache.get(("k", 0)) is None  # oldest inserted: evicted
    assert cache.get(("k", 39)) == ("payload", 0.5, "log")  # newest: retained
    stats = cache.stats
    assert stats["cache_evictions"] == 8  # cap evictions are counted


def test_skip_fifo_cap_evicts_oldest_first() -> None:
    cache = CompressionCache(ttl_seconds=3600, max_entries=32)
    for i in range(40):
        cache.mark_skip(("s", i))

    assert cache.skip_size == 32
    assert cache.is_skipped(("s", 0)) is False  # oldest inserted: evicted
    assert cache.is_skipped(("s", 39)) is True  # newest: retained


def test_default_cap_is_enforced() -> None:
    """Default construction (the router's ``CompressionCache()``) is bounded."""
    cache = CompressionCache(ttl_seconds=3600)
    overflow = 10
    for i in range(router_cache_module.DEFAULT_MAX_ENTRIES_PER_TIER + overflow):
        cache.put(i, "p", 0.5, "log")
    assert cache.size == router_cache_module.DEFAULT_MAX_ENTRIES_PER_TIER


# ---------------------------------------------------------------------------
# COR-21 follow-up (FIX 4): metric counters are exact under the lock
# ---------------------------------------------------------------------------


def test_miss_counter_is_exact_under_concurrency() -> None:
    """Formerly the lock-free ``+=`` could lose increments (benign but
    inexact). Under the lock, 8 threads x 500 distinct-key misses must count
    to exactly 4000."""
    cache = CompressionCache()
    n_threads, n_ops = 8, 500
    counter = threading.local()

    def worker() -> None:
        counter.tid = threading.get_ident()
        for i in range(n_ops):
            cache.get(("never-inserted", counter.tid, i))

    assert _hammer(worker, n_threads=n_threads) == []
    stats = cache.stats
    assert stats["cache_misses"] == n_threads * n_ops
    assert stats["cache_hits"] == 0
