"""Rust-backed tag protector — keep custom XML tags away from compressors.

Restored in Engine P2-11 (originally excised in Great-Excision Chunk 7
when its only consumer, the retired ML text compressor, disappeared).
The new load-bearing consumer is the Rust ``TextCrusher``
(``crates/furl-core/src/transforms/text_crusher.rs``), which calls
``protect_tags`` / ``restore_tags`` natively; this module re-exposes the
same primitives to Python callers and tests.

This module is a thin shim that:

1. Routes ``protect_tags`` / ``restore_tags`` through PyO3 so callers
   pick up the single-pass Rust walker (and the five bug fixes that
   ride along — see the crate-level docs in the Rust source).
2. Re-exports the legacy import surface (``KNOWN_HTML_TAGS``,
   ``_is_html_tag``) so historical callers and the test suite work
   without same-PR refactors.

# Bug fixes the Rust port carries (and this shim therefore inherits)

* **#1: O(n²) on nested custom tags.** Python iterated a regex
  scan-and-replace loop until stable, restarting from the top after
  every replacement. Rust walks once, in linear time on input length.
* **#2: First-occurrence replace bug.** ``str.replace(orig, ph, 1)``
  replaces the FIRST textual match, not the matched offset. Two
  identical custom-tag blocks collapsed to one placeholder + a stray
  duplicate of the second block. The Rust walker stitches output by
  offset — distinct blocks always get distinct placeholders.
* **#3: Silent 50-iteration cap.** Python had a hard ``max_iterations
  = 50`` safety limit that quietly truncated tag protection on deeply
  nested input. The Rust walker is bounded by input length only.
* **#4: Self-closing pass duplicate-replace risk.** Python ran a
  second loop with the same first-occurrence-replace bug for
  self-closers. Rust handles them in the same single pass.
* **#5: Placeholder collision.** If the input contained a literal
  ``{{FURL_TAG_…}}`` substring, Python silently let the collision
  stand. Rust detects it and salts the prefix.

# PERF-15 (fixed during this restoration)

``restore_tags`` is now a single left-to-right scan (aho-corasick,
leftmost-longest) instead of a per-block ``str.replace`` loop:

* each placeholder substitutes at most ONCE — the first occurrence
  wins; compressor-fabricated duplicates stay verbatim (WARN logged);
* substituted originals are never rescanned, so a restored block whose
  body contains a later placeholder literal is not corrupted;
* cost is O(text + Σ placeholder lengths), not O(blocks × text).
"""

from __future__ import annotations

import logging
from typing import cast

from furl_ctx._core import (
    is_html_tag as _rust_is_html_tag,
)
from furl_ctx._core import (
    known_html_tag_names as _rust_known_html_tag_names,
)
from furl_ctx._core import (
    protect_tags as _rust_protect_tags,
)
from furl_ctx._core import (
    restore_tags as _rust_restore_tags,
)

logger = logging.getLogger(__name__)


# Pulled from Rust at import time so the canonical list lives in one
# place. The frozenset shape is the legacy public surface — tests and
# the integration test ask for membership / size on this object.
KNOWN_HTML_TAGS: frozenset[str] = frozenset(_rust_known_html_tag_names())


def _is_html_tag(tag_name: str) -> bool:
    """Case-insensitive HTML5 tag check.

    Kept as a private name (with the underscore) because the Python
    test file imports ``_is_html_tag`` directly. Delegates to the Rust
    implementation so the two languages can't drift on what counts as
    "HTML".
    """
    return bool(_rust_is_html_tag(tag_name))


def protect_tags(
    text: str,
    compress_tagged_content: bool = False,
) -> tuple[str, list[tuple[str, str]]]:
    """Protect custom/workflow XML tags from text compression.

    Args:
        text: Input text potentially containing XML tags.
        compress_tagged_content: If False (default), protect entire
            ``<tag>content</tag>`` block verbatim. If True, only
            protect the tag markers; content between them is exposed
            for compression.

    Returns:
        Tuple of ``(cleaned_text, protected_blocks)`` where each
        protected block is a ``(placeholder, original)`` pair. Hand
        the full block list to :func:`restore_tags` after the
        compressor has run.
    """
    cleaned, blocks = _rust_protect_tags(text, compress_tagged_content)
    # The Rust binding hands us a list of plain Python tuples already.
    return cast("str", cleaned), cast("list[tuple[str, str]]", blocks)


def restore_tags(
    text: str,
    protected_blocks: list[tuple[str, str]],
) -> str:
    """Restore protected tag blocks after compression.

    Args:
        text: Compressed text with placeholders.
        protected_blocks: List from :func:`protect_tags`.

    Returns:
        Text with placeholders swapped back to originals in ONE
        left-to-right pass (PERF-15): each placeholder substitutes at
        most once — the first occurrence wins and any later duplicate
        of the same placeholder is left verbatim. If the compressor
        stripped or rewrote a placeholder entirely, the wrap is
        **discarded** — the compressed text is returned as-is for
        that block, and the original tag bytes are NOT re-injected
        anywhere (the Hotfix-A9 behavior; the old "append the orphan
        tag at the trailing edge" fallback produced silently malformed
        XML on production traffic).

        Each lost placeholder emits a structured ERROR-level log
        (``event=tag_protector_placeholder_lost``) so operators can
        alert on the corruption rather than have it disappear into
        a WARN line. Token validation downstream is responsible for
        catching cases where the discard regressed the final output.
    """
    return cast("str", _rust_restore_tags(text, protected_blocks))


__all__ = [
    "KNOWN_HTML_TAGS",
    "_is_html_tag",
    "protect_tags",
    "restore_tags",
]
