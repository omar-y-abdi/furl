"""tag_protector restoration pins (Engine P2-11).

The module was excised in Great-Excision Chunk 7 (zero consumers after
the ML text compressor retired) and restored as TextCrusher's protection
rail. These tests pin the Python-facing surface:

1. Round-trip correctness (protect → restore == original).
2. The legacy import surface (``KNOWN_HTML_TAGS``, ``_is_html_tag``).
3. PERF-15: ``restore_tags`` is a single left-to-right scan — each
   placeholder substitutes at most once (duplicates stay verbatim) and
   substituted originals are never rescanned.
4. Hotfix-A9 discard-wrap semantics for lost placeholders.

The algorithmic depth (nesting, malformed input, proptest invariants)
is pinned Rust-side in ``tag_protector.rs``.
"""

from __future__ import annotations

from furl_ctx.transforms.tag_protector import (
    KNOWN_HTML_TAGS,
    _is_html_tag,
    protect_tags,
    restore_tags,
)

# ─── Legacy import surface ───────────────────────────────────────────────────


class TestLegacySurface:
    def test_known_html_tags_is_frozenset_with_standard_elements(self) -> None:
        assert isinstance(KNOWN_HTML_TAGS, frozenset)
        for tag in ("div", "p", "span", "code", "pre", "table"):
            assert tag in KNOWN_HTML_TAGS
        assert "system-reminder" not in KNOWN_HTML_TAGS
        assert len(KNOWN_HTML_TAGS) > 100

    def test_is_html_tag_case_insensitive(self) -> None:
        assert _is_html_tag("DIV")
        assert _is_html_tag("Span")
        assert not _is_html_tag("system-reminder")
        assert not _is_html_tag("tool_call")


# ─── Protect / restore round-trip ────────────────────────────────────────────


class TestRoundTrip:
    def test_custom_tag_protected_and_restored(self) -> None:
        text = "Before <system-reminder>Important rule</system-reminder> After"
        cleaned, blocks = protect_tags(text)
        assert "<system-reminder>" not in cleaned
        assert "Important rule" not in cleaned
        assert len(blocks) == 1
        assert restore_tags(cleaned, blocks) == text

    def test_html_tags_not_protected(self) -> None:
        text = "<div>HTML stays</div> but <thinking>this hides</thinking>"
        cleaned, blocks = protect_tags(text)
        assert "<div>HTML stays</div>" in cleaned
        assert "<thinking>" not in cleaned
        assert len(blocks) == 1
        assert restore_tags(cleaned, blocks) == text

    def test_marker_only_mode_exposes_body(self) -> None:
        text = "<context>compressible body</context>"
        cleaned, blocks = protect_tags(text, compress_tagged_content=True)
        assert "compressible body" in cleaned
        assert "<context>" not in cleaned
        assert len(blocks) == 2
        assert restore_tags(cleaned, blocks) == text

    def test_duplicate_blocks_get_distinct_placeholders(self) -> None:
        text = "<t>same</t> mid <t>same</t>"
        cleaned, blocks = protect_tags(text)
        assert len(blocks) == 2
        assert blocks[0][0] != blocks[1][0]
        assert restore_tags(cleaned, blocks) == text


# ─── PERF-15: single-scan restore ────────────────────────────────────────────


class TestPerf15SingleScan:
    def test_duplicate_placeholder_substitutes_once(self) -> None:
        """A compressor that duplicates a placeholder must not duplicate
        the protected block: first occurrence wins, the duplicate stays
        verbatim."""
        blocks = [("{{FURL_TAG_0}}", "<system-reminder>rule</system-reminder>")]
        compressed = "head {{FURL_TAG_0}} mid {{FURL_TAG_0}} tail"
        restored = restore_tags(compressed, blocks)
        assert restored == ("head <system-reminder>rule</system-reminder> mid {{FURL_TAG_0}} tail")
        assert restored.count("<system-reminder>") == 1

    def test_substituted_originals_never_rescanned(self) -> None:
        """A restored block whose body contains a LATER placeholder literal
        must not be corrupted by a second substitution inside it."""
        blocks = [
            ("{{FURL_TAG_0}}", "<doc>literal {{FURL_TAG_1}} inside</doc>"),
            ("{{FURL_TAG_1}}", "<b>2</b>"),
        ]
        compressed = "a {{FURL_TAG_0}} b {{FURL_TAG_1}} c"
        restored = restore_tags(compressed, blocks)
        assert restored == "a <doc>literal {{FURL_TAG_1}} inside</doc> b <b>2</b> c"

    def test_out_of_order_placeholders_restore(self) -> None:
        blocks = [
            ("{{FURL_TAG_0}}", "<a>first</a>"),
            ("{{FURL_TAG_1}}", "<b>second</b>"),
        ]
        restored = restore_tags("{{FURL_TAG_1}} then {{FURL_TAG_0}}", blocks)
        assert restored == "<b>second</b> then <a>first</a>"


# ─── Hotfix-A9: discard-wrap on loss ─────────────────────────────────────────


class TestDiscardWrap:
    def test_lost_placeholder_discards_wrap(self) -> None:
        blocks = [("{{FURL_TAG_0}}", "<tag>data</tag>")]
        compressed = "text without the placeholder"
        restored = restore_tags(compressed, blocks)
        assert restored == compressed
        assert "<tag>" not in restored

    def test_partial_loss_keeps_present_drops_lost(self) -> None:
        blocks = [
            ("{{FURL_TAG_0}}", "<a>1</a>"),
            ("{{FURL_TAG_1}}", "<lost>x</lost>"),
        ]
        restored = restore_tags("head {{FURL_TAG_0}} tail", blocks)
        assert restored == "head <a>1</a> tail"
        assert "<lost" not in restored

    def test_empty_blocks_passthrough(self) -> None:
        assert restore_tags("untouched", []) == "untouched"
