"""LogTemplate → compression dispatch routing (NR2-3b).

Pins the wiring of the already-tested, lossless :func:`encode_verified`
encoder into the LOG strategy arm of :class:`StrategyDispatcher`:

* a templatable BUILD_OUTPUT log routes to LogTemplate, shipping the wire;
* a structureless BUILD_OUTPUT log falls through to the historical path;
* ``enable_log_template=False`` is byte-identical to that historical path;
* ``lossless_only=True`` KEEPS LogTemplate live (it is lossless-or-None,
  the SmartCrusher guarantee — strict mode is lossless-OR-passthrough);
* the token-unit savings gate declines a wire that does not beat content.

Mirrors ``test_tabular_ingest.py``: a real :class:`ContentRouter` driven
with the production token counter (the whitespace word proxy mis-measures
low-whitespace wire so badly the savings gate would never agree with it).
"""

from __future__ import annotations

import hashlib
import logging

import pytest

from furl_ctx.cache.compression_store import reset_compression_store
from furl_ctx.tokenizers import get_tokenizer
from furl_ctx.transforms.content_detector import ContentType, detect_content_type
from furl_ctx.transforms.content_router import ContentRouter, ContentRouterConfig
from furl_ctx.transforms.log_template import encode_verified
from furl_ctx.transforms.router_policy import CompressionStrategy

# Real token counter (COR-17): apply() always threads one in production. The
# savings gate compares wire vs content in THESE units, not whitespace words.
_COUNT = get_tokenizer("claude-sonnet-4-5-20250929").count_text


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FURL_WORKSPACE_DIR", str(tmp_path))
    reset_compression_store()
    yield
    reset_compression_store()


# ─── Fixtures ────────────────────────────────────────────────────────────────


def templatable_log() -> str:
    """BUILD_OUTPUT with a mineable skeleton (fixed words + varying params).

    Sized so the wire stays under ``_OFFLOAD_MIN_CHARS`` (4000) and beats the
    ``_OFFLOAD_TRIGGER_RATIO`` (0.9): LogTemplate ships the wire clean on the
    DEFAULT config, with no downstream CCR offload re-processing it."""
    lines = [
        f"INFO [worker-{i % 4}] processed batch id={1000 + i} "
        f"rows={i * 3} status=ok latency={i}.{i}ms"
        for i in range(40)
    ]
    return "\n".join(lines)


def structureless_log() -> str:
    """BUILD_OUTPUT shape with NO mineable template: every line is a distinct
    high-entropy digest, so ``encode_verified`` returns None and the LOG arm
    falls through to the historical lossy path."""
    lines = [
        f"ERROR {hashlib.sha1(str(i).encode()).hexdigest()} failed at {i * 7919}"  # noqa: S324
        for i in range(30)
    ]
    return "\n".join(lines)


# ─── Fixture preconditions (the tests below only mean what these assert) ──────


def test_templatable_log_precondition() -> None:
    content = templatable_log()
    assert detect_content_type(content).content_type is ContentType.BUILD_OUTPUT
    enc = encode_verified(content)
    assert enc is not None, "fixture must be minable, else the routing test is vacuous"
    assert _COUNT(enc.wire) < _COUNT(content), "wire must win in token units"


def test_structureless_log_precondition() -> None:
    content = structureless_log()
    assert detect_content_type(content).content_type is ContentType.BUILD_OUTPUT
    assert encode_verified(content) is None, "fixture must decline, else fall-through is vacuous"


# ─── Routing: LogTemplate wins the LOG arm ───────────────────────────────────


def test_templatable_log_routes_to_log_template(caplog) -> None:
    content = templatable_log()
    enc = encode_verified(content)
    assert enc is not None

    with caplog.at_level(logging.DEBUG, logger="furl_ctx.transforms.content_router"):
        result = ContentRouter().compress(content, token_counter=_COUNT)

    assert result.compressed == enc.wire, "LogTemplate must ship the verified wire"
    assert result.strategy_used is CompressionStrategy.LOG
    assert "log_template" in result.strategy_chain
    # Mining stats surfaced on the same debug channel the tabular branch uses.
    stats = [r for r in caplog.records if "log_template_encoded" in r.getMessage()]
    assert stats, "template_count/templated_lines/verbatim_lines must be recorded"
    line = stats[0].getMessage()
    assert f'"template_count":{enc.template_count}' in line
    assert f'"templated_lines":{enc.templated_lines}' in line
    assert f'"verbatim_lines":{enc.verbatim_lines}' in line


def test_structureless_log_falls_through(caplog) -> None:
    content = structureless_log()
    with caplog.at_level(logging.DEBUG, logger="furl_ctx.transforms.content_router"):
        result = ContentRouter().compress(content, token_counter=_COUNT)
    assert "log_template" not in result.strategy_chain
    assert not [r for r in caplog.records if "log_template_encoded" in r.getMessage()]


# ─── Flag off: byte-identical to the historical path on BOTH corpora ─────────


@pytest.mark.parametrize(
    "content_fn",
    [pytest.param(templatable_log, id="templatable"), pytest.param(structureless_log, id="noise")],
)
def test_flag_off_matches_historical_no_savings_baseline(content_fn) -> None:
    """Flag off ships EXACTLY the pre-feature output. On the LOG arm the only
    historical compressor is the lossy LogCompressor, which finds no savings on
    either fixture (varied params / high entropy) and hands back the raw bytes —
    so today's byte-identical baseline is ``content`` itself. This is anchored
    to that baseline, not merely to the flag-on output."""
    content = content_fn()
    off = ContentRouter(ContentRouterConfig(enable_log_template=False)).compress(
        content, token_counter=_COUNT
    )
    assert "log_template" not in off.strategy_chain
    assert off.compressed == content, "flag off must reproduce the historical LOG-arm output"


def test_flag_flip_changes_only_templatable_output() -> None:
    """The flag is load-bearing: on templatable content it flips the outcome
    (wire vs raw baseline); on structureless content it is a no-op."""
    templatable = templatable_log()
    on_t = ContentRouter().compress(templatable, token_counter=_COUNT)
    off_t = ContentRouter(ContentRouterConfig(enable_log_template=False)).compress(
        templatable, token_counter=_COUNT
    )
    assert on_t.compressed != off_t.compressed, "flag must engage on templatable content"

    noise = structureless_log()
    on_n = ContentRouter().compress(noise, token_counter=_COUNT)
    off_n = ContentRouter(ContentRouterConfig(enable_log_template=False)).compress(
        noise, token_counter=_COUNT
    )
    assert on_n.compressed == off_n.compressed, "flag must be a no-op on structureless content"


# ─── lossless_only KEEPS LogTemplate live (the pinned NR2-3b decision) ───────


def test_lossless_only_keeps_log_template_live() -> None:
    """DECISION: LogTemplate stays live under ``lossless_only``. It is
    lossless-or-None (``encode_verified`` self-verifies the round-trip),
    exactly the SmartCrusher guarantee — whose arm is likewise NOT gated by
    ``lossless_only`` — and it writes no CCR store. Strict mode is
    lossless-OR-passthrough, not passthrough-only, so a proven-reversible
    recode is admissible; the lossy log/search/diff arms stay gated off."""
    content = templatable_log()
    enc = encode_verified(content)
    assert enc is not None

    result = ContentRouter(ContentRouterConfig(lossless_only=True)).compress(
        content, token_counter=_COUNT
    )
    assert result.compressed == enc.wire, "strict mode must still ship the lossless wire"
    assert "log_template" in result.strategy_chain


# ─── Savings gate: a wire that does not beat content in TOKENS falls through ──


def test_savings_gate_declines_when_wire_not_smaller_in_tokens() -> None:
    """``encode_verified`` may succeed (code-point win) yet the wire can cost
    MORE tokens than the source. A token counter that inflates the wire proves
    the gate is measured in the injected units: the arm must decline and fall
    through, never shipping a token-larger wire."""
    content = templatable_log()
    enc = encode_verified(content)
    assert enc is not None

    # Adversarial counter: the wire is charged one unit per character (huge),
    # the source its honest token count. wire_tokens >= content_tokens.
    def _inflate_wire(text: str) -> int:
        return len(text) if text == enc.wire else _COUNT(text)

    assert _inflate_wire(enc.wire) >= _inflate_wire(content)
    result = ContentRouter().compress(content, token_counter=_inflate_wire)
    assert result.compressed != enc.wire, "a token-larger wire must not ship"
    assert "log_template" not in result.strategy_chain
