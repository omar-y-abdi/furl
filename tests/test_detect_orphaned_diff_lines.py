"""P0-1: orphaned ``+++`` lines must not panic the detect bridge.

Defect being pinned
-------------------
``unidiff`` 0.4.0 executes ``source_file.clone().unwrap()`` when it meets
a ``+++ <name>`` target-file header with no preceding ``--- <name>``
source header (unidiff-0.4.0/src/lib.rs:665) — an *orphaned* ``+++``
line. ``set -x`` shell traces produce exactly that shape: three-level
nested command expansions are prefixed ``+++ ``. Pre-fix, the panic
crossed the FFI as ``pyo3_runtime.PanicException`` (a ``BaseException``)
out of ``furl_ctx._core.detect_content_type`` — the ONE pyo3 bridge the
router's ``_detect_content`` calls on EVERY message, i.e. the hook's
hottest path. ``compress()`` survived only via its outermost
``BaseException`` fail-open (COR-7), which reverted the WHOLE request
and recorded the panic in ``result.error``.

The fix is two-layered (both Rust-side):

* ``furl-core`` ``is_diff`` restores the upstream ``catch_unwind``: a
  panicking parse means "not a diff we can process" — the content falls
  through to PlainText routing (fail-open passthrough, no crash, no
  reverted request).
* the ``detect_content_type`` bridge itself now carries the COR-7
  catch_unwind→PyRuntimeError wrapper, so any OTHER panic in the
  detection chain surfaces as an ordinary ``Exception`` instead of a
  ``BaseException`` (belt-and-braces).

RED evidence (pre-fix, captured 2026-07-03): ``detect_content_type`` on
the trace below raised ``pyo3_runtime.PanicException: called
Option::unwrap() on a None value``.
"""

from __future__ import annotations

from furl_ctx._core import detect_content_type as _rust_detect
from furl_ctx.compress import compress


def _set_x_trace(n_blocks: int = 40) -> str:
    """A ``set -x``-style shell trace with orphaned ``+++`` lines.

    Every third line is a three-level nested expansion (``+++ cmd``) —
    unidiff reads it as a target-file header with no source header
    before it, the exact panic shape. Lines are varied (indexed) so no
    dedup/compression stage can legitimately rewrite the payload; the
    only correct routing is PlainText passthrough.
    """
    lines = []
    for i in range(n_blocks):
        lines.append(f"+ process item {i}")
        lines.append(f"++ compute checksum {i}")
        lines.append(f"+++ readlink -f /data/items/{i}")
    return "\n".join(lines) + "\n"


class TestDetectBridgeContainment:
    """`furl_ctx._core.detect_content_type` — the hottest bridge."""

    def test_orphaned_plus_lines_do_not_panic_the_bridge(self) -> None:
        """RED pre-fix: PanicException (BaseException) straight through
        the FFI. GREEN: the contained detector treats the trace as
        not-a-diff and returns the PlainText tag."""
        result = _rust_detect(_set_x_trace())
        assert result.content_type == "text"

    def test_orphan_before_valid_diff_does_not_panic(self) -> None:
        """The orphan precedes an otherwise-valid diff; unidiff panics at
        the first orphan, so containment classifies the whole input as
        not-a-diff (passthrough beats a crash)."""
        mixed = "+++ orphan-target-first\n--- a/foo.py\n+++ b/foo.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
        result = _rust_detect(mixed)
        assert result.content_type == "text"

    def test_valid_diff_still_detected(self) -> None:
        """Containment must not eat true positives: a well-formed diff
        keeps routing to the diff compressor."""
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,1 +1,2 @@\n"
            " def hello():\n"
            '+    print("new")\n'
        )
        result = _rust_detect(diff)
        assert result.content_type == "diff"


class TestCompressFailOpen:
    """Full stack: parser → router → detect bridge → fail-open."""

    def test_compress_passes_set_x_trace_through_without_crash(self) -> None:
        """A tool output full of orphaned ``+++`` lines must ride through
        ``compress()`` untouched: routed PlainText → passthrough. Pre-fix
        this tripped the outermost BaseException fail-open — the whole
        request reverted and ``result.error`` carried the panic text; the
        assertion on ``result.error is None`` pins the difference between
        "survived via fail-open" and "processed normally"."""
        trace = _set_x_trace()
        messages = [
            {"role": "user", "content": "run the deploy and show the trace"},
            {"role": "tool", "tool_call_id": "t1", "content": trace},
        ]

        result = compress(messages, model="gpt-4o")

        assert result.error is None, (
            "detect-bridge panic reached the fail-open boundary instead of "
            f"being contained at is_diff: {result.error!r}"
        )
        assert result.messages[1]["content"] == trace, (
            "set -x trace did not pass through byte-identically"
        )
