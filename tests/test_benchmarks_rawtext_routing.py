"""Routing pins for the four raw-TEXT benchmark datasets (EFF-6).

Each dataset must reach its intended compressor through the REAL
ContentRouter (detection → strategy mapping → dispatch), not through a
direct compressor call:

* ``ci_log``       → LogCompressor    (strategy ``log``)
* ``grep_raw``     → SearchCompressor (strategy ``search``)
* ``diff_raw``     → DiffCompressor   (strategy ``diff``)
* ``markdown_doc`` → TextCrusher      (strategy ``text``)

Plus one E2E pin through the public ``compress()`` (the exact surface the
benchmark harness measures), and a pin for the documented fence behaviour:
markdown WITH ``` fences trips ``is_mixed_content`` and routes MIXED, whose
prose sections still reach TextCrusher — the committed dataset uses indented
code blocks to hold the PURE TextCrusher route.
"""

from __future__ import annotations

import pytest

from benchmarks.datasets import (
    Dataset,
    build_ci_log_dataset,
    build_diff_raw_dataset,
    build_grep_raw_dataset,
    build_markdown_doc_dataset,
)
from benchmarks.metrics import _reset_engine_state
from furl_ctx.transforms.content_router import (
    CompressionStrategy,
    ContentRouter,
    ContentRouterConfig,
)

# (dataset builder, expected router strategy) — the EFF-6 routing contract.
_ROUTE_PINS = (
    (build_ci_log_dataset, CompressionStrategy.LOG),
    (build_grep_raw_dataset, CompressionStrategy.SEARCH),
    (build_diff_raw_dataset, CompressionStrategy.DIFF),
    (build_markdown_doc_dataset, CompressionStrategy.TEXT),
)


def _raw_text(dataset: Dataset) -> str:
    """The raw tool-output text of a raw-text dataset (message 1 content)."""
    content = dataset.messages[1]["content"]
    assert isinstance(content, str)
    return content


@pytest.mark.parametrize(
    ("builder", "expected"),
    _ROUTE_PINS,
    ids=[b.__name__.removeprefix("build_").removesuffix("_dataset") for b, _ in _ROUTE_PINS],
)
def test_raw_text_dataset_routes_to_intended_compressor(builder, expected) -> None:
    """The real ContentRouter must pick the intended strategy — PURE, not
    mixed/passthrough — and actually compress (a passthrough would mean the
    benchmark exercises nothing)."""
    dataset = builder()
    router = ContentRouter(ContentRouterConfig())
    result = router.compress(_raw_text(dataset))

    assert result.strategy_used is expected, (
        f"{dataset.name}: routed {result.strategy_used} (chain={result.strategy_chain}), "
        f"expected {expected}"
    )
    assert result.sections_processed == 1, (
        f"{dataset.name}: split into {result.sections_processed} sections — not a pure route"
    )
    assert result.compressed != result.original, f"{dataset.name}: compressor was a no-op"
    assert result.compression_ratio < 1.0


def test_ci_log_routes_log_end_to_end_through_compress() -> None:
    """E2E pin on the exact surface the benchmark measures: compress() must
    record a ``router:log:<ratio>`` transform for the ci_log dataset."""
    from furl_ctx import compress

    _reset_engine_state()
    dataset = build_ci_log_dataset()
    result = compress(dataset.messages, model="gpt-4o")
    log_transforms = [t for t in result.transforms_applied if t.startswith("router:log:")]
    assert log_transforms, (
        f"no router:log transform fired E2E; transforms={result.transforms_applied}"
    )
    assert result.tokens_after < result.tokens_before


def test_markdown_with_code_fences_routes_mixed_with_text_sections() -> None:
    """Documented engine behaviour (why the dataset avoids ``` fences): a
    fence plus prose trips is_mixed_content → MIXED; the prose sections still
    route to TextCrusher (TEXT appears in the section routing log)."""
    dataset = build_markdown_doc_dataset()
    fenced = _raw_text(dataset).replace(
        "    pip install headroom",
        "```bash\npip install headroom\n```",
        1,
    )
    router = ContentRouter(ContentRouterConfig())
    result = router.compress(fenced)
    assert result.strategy_used is CompressionStrategy.MIXED
    section_strategies = {decision.strategy for decision in result.routing_log}
    assert CompressionStrategy.TEXT in section_strategies, (
        f"no prose section reached TextCrusher: {section_strategies}"
    )


def test_raw_text_dataset_items_are_distinct_lines_of_the_raw_text() -> None:
    """Items (the retention unit) must be distinct non-blank lines, each
    verbatim-present in the raw capture."""
    for builder, _ in _ROUTE_PINS:
        dataset = builder()
        raw = _raw_text(dataset)
        assert len(dataset.items) == len(set(dataset.items)), f"{dataset.name}: duplicate items"
        assert len(dataset.items) >= 50 or dataset.name == "markdown_doc"
        for item in dataset.items:
            assert isinstance(item, str) and item.strip()
            assert item in raw


def test_ci_log_shape_contract() -> None:
    """The CI log must honour the shape constraints that decide routing
    (documented in rawtext_sources): ≥200 lines, no grep-shaped lines, no
    JSON-block-leading lines — plus the realism the plan asks for
    (timestamps, warnings, a traceback)."""
    import re

    raw = _raw_text(build_ci_log_dataset())
    lines = raw.splitlines()
    assert len(lines) >= 200
    grep_shaped = [ln for ln in lines if re.match(r"^\S+:\d+:", ln)]
    assert not grep_shaped, f"grep-shaped lines would pull detection to SEARCH: {grep_shaped[:3]}"
    json_leading = [ln for ln in lines if ln.lstrip()[:1] in ("[", "{") and ln.strip()]
    assert not json_leading, f"JSON-block-leading lines trip the mixed gate: {json_leading[:3]}"
    assert "Traceback (most recent call last):" in raw
    assert "WARNING" in raw and "WARN" in raw
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", raw), "no timestamps"


def test_ci_log_is_deterministic() -> None:
    """Same seed ⇒ same bytes (the committed snapshot is re-derivable)."""
    from benchmarks.rawtext_sources import synth_ci_log

    assert synth_ci_log() == synth_ci_log()


def test_all_datasets_includes_the_four_raw_text_datasets() -> None:
    from benchmarks.datasets import all_datasets

    names = [d.name for d in all_datasets()]
    assert len(names) == len(set(names))
    for expected in ("ci_log", "grep_raw", "diff_raw", "markdown_doc"):
        assert expected in names, f"{expected} not wired into all_datasets(): {names}"
