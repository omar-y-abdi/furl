"""count_text memoizes large repeated strings (perf) without changing the count.

The router / min_ratio gate re-count the same multi-MB content many times per
compress(); tiktoken is O(n), so that dominated latency on large inputs. The memo
must be a pure speedup: a cache hit returns the exact same count as a fresh encode.
"""

from __future__ import annotations

from furl_ctx.tokenizers.tiktoken_counter import TiktokenCounter


def test_large_repeated_string_is_encoded_once() -> None:
    counter = TiktokenCounter("gpt-4o")
    big = "the quick brown fox " * 5000
    assert len(big) >= counter._COUNT_CACHE_MIN_LEN

    calls = {"n": 0}
    real = counter._encode_tolerant

    def counting(text: str) -> list[int]:
        calls["n"] += 1
        return real(text)

    counter._encode_tolerant = counting  # type: ignore[method-assign]

    first = counter.count_text(big)
    second = counter.count_text(big)
    third = counter.count_text(big)

    assert first == second == third  # identical count every time
    assert calls["n"] == 1  # encoded once, then served from cache


def test_cache_hit_matches_a_fresh_uncached_encode() -> None:
    cached = TiktokenCounter("gpt-4o")
    reference = TiktokenCounter("gpt-4o")
    reference._COUNT_CACHE_MIN_LEN = 10**12  # disable caching on the reference

    big = "lorem ipsum dolor sit amet " * 4000
    assert cached.count_text(big) == reference.count_text(big)


def test_small_strings_are_not_cached() -> None:
    counter = TiktokenCounter("gpt-4o")
    counter.count_text("hello world")
    assert counter._count_cache == {}  # below threshold → never stored


def test_cache_stays_bounded_by_bytes() -> None:
    counter = TiktokenCounter("gpt-4o")
    counter._COUNT_CACHE_MAX_BYTES = 3 * counter._COUNT_CACHE_MIN_LEN  # tiny budget for the test
    filler = "x" * counter._COUNT_CACHE_MIN_LEN
    for i in range(8):
        counter.count_text(f"{i}-{filler}")
    assert counter._count_cache_bytes <= counter._COUNT_CACHE_MAX_BYTES
    assert len(counter._count_cache) <= 3  # oldest evicted once the byte budget is hit
