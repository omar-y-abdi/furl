"""Raw-TEXT benchmark content that is not captured from a live command.

Two sources live here so ``datasets.py`` stays focused on capture/wiring:

* :func:`synth_ci_log` — a deterministic, realistically-shaped CI log
  (npm install + cargo build + pytest run with warnings and a traceback).
  A real CI run cannot be captured reproducibly from this machine, so the
  text is synthesized ONCE from a fixed seed and snapshotted like every
  other dataset; the seed and the generator are the provenance.
* :data:`MARKDOWN_DOC` — a README-shaped markdown/prose document
  (headers, lists, indented code blocks, paragraphs). Indented code
  blocks (valid markdown) are used instead of ``` fences deliberately:
  a fence plus prose trips the router's ``is_mixed_content`` gate and
  routes MIXED (prose sections still reach TextCrusher, but the dataset
  is meant to pin the PURE TextCrusher route). The fence behaviour is
  pinned separately in the routing tests.

Both are pure (no I/O, no ambient state): the same inputs always produce
the same text, so the committed snapshot can be re-derived and audited.

Shape constraints the CI log honours (they decide real routing):

* No line matches ``^\\S+:\\d+:`` — leading ISO-with-colons timestamps or
  pytest's short ``path.py:87: Error`` form would match the grep
  ``file:line:`` shape and pull detection toward SEARCH_RESULTS; the
  pytest failure is therefore rendered in native-traceback style and app
  log lines use python-logging's space-separated asctime.
* No line starts with ``[`` or ``{`` — the mixed-content gate reads those
  as JSON-block starts.
* WARN/INFO/FAILED/Traceback/timestamp/separator lines are abundant —
  exactly the signals the BUILD_OUTPUT detector scores.
"""

from __future__ import annotations

import random

CI_LOG_SEED = 20260703

_NPM_PHASE: tuple[str, ...] = (
    "$ npm ci --no-audit --no-fund",
    "npm WARN deprecated inflight@1.0.6: This module is not supported",
    "npm WARN deprecated glob@7.2.3: Glob versions prior to v9 are no longer supported",
    "npm WARN deprecated rimraf@3.0.2: Rimraf versions prior to v4 are no longer supported",
    "added 412 packages in 9s",
    "",
)

_CARGO_CRATES: tuple[str, ...] = (
    "proc-macro2 v1.0.86",
    "quote v1.0.36",
    "unicode-ident v1.0.12",
    "syn v2.0.72",
    "serde v1.0.204",
    "serde_derive v1.0.204",
    "libc v0.2.155",
    "autocfg v1.3.0",
    "memchr v2.7.4",
    "regex-syntax v0.8.4",
    "aho-corasick v1.1.3",
    "regex-automata v0.4.7",
    "regex v1.10.5",
    "thiserror v2.0.18",
    "thiserror-impl v2.0.18",
    "anyhow v1.0.86",
    "once_cell v1.19.0",
    "smallvec v1.13.2",
    "hashbrown v0.14.5",
    "indexmap v2.2.6",
    "itoa v1.0.11",
    "ryu v1.0.18",
    "serde_json v1.0.120",
    "furl-core v0.9.1",
)

_CARGO_WARNING: tuple[str, ...] = (
    "warning: unused variable: `retry_budget`",
    "  --> crates/furl-core/src/planning.rs:412:9",
    "    |",
    "412 |     let retry_budget = config.retry_budget;",
    "    |         ^^^^^^^^^^^^ help: if this is intentional, prefix it with an underscore",
    "    |",
    "    = note: `#[warn(unused_variables)]` on by default",
    "warning: `furl-core` (lib) generated 1 warning",
    "    Finished `release` profile [optimized] target(s) in 41.28s",
    "",
)

_PYTEST_HEADER: tuple[str, ...] = (
    "$ .venv/bin/python -m pytest tests -q -p no:cacheprovider",
    "============================= test session starts ==============================",
    "platform linux -- Python 3.12.4, pytest-8.2.2, pluggy-1.5.0",
    "rootdir: /home/runner/work/headroom/headroom",
    "configfile: pyproject.toml",
    "plugins: cov-5.0.0, xdist-3.6.1, timeout-2.3.1",
    "collected 214 items",
    "",
)

_PYTEST_FAILURE: tuple[str, ...] = (
    "",
    "=================================== FAILURES ===================================",
    "_______________________ test_router_block_token_accounting ____________________",
    "Traceback (most recent call last):",
    '  File "/home/runner/work/headroom/headroom/tests/'
    'test_router_block_token_accounting.py", line 87, in '
    "test_router_block_token_accounting",
    '    assert result.tokens_after <= budget, "block accounting overflow"',
    "AssertionError: block accounting overflow",
    "=========================== short test summary info ===========================",
    "FAILED tests/test_router_block_token_accounting.py -- AssertionError",
    "================== 1 failed, 209 passed, 4 skipped in 38.11s ==================",
    "##[error]Process completed with exit code 1.",
)

_APP_MODULES: tuple[str, ...] = (
    "pipeline",
    "router",
    "crusher",
    "store",
    "tokenizer",
    "aligner",
    "dedup",
    "retrieval",
    "markers",
    "lifecycle",
)


def synth_ci_log(seed: int = CI_LOG_SEED, n_app_lines: int = 150) -> str:
    """Deterministic npm + cargo + pytest CI log text (≥200 lines).

    The seeded RNG varies only realistic per-line details (timestamps,
    worker module, durations); the structure — install warnings, build
    warning block, per-case INFO/WARNING app logs, one native-traceback
    failure, run summary — is fixed. Same ``(seed, n_app_lines)`` ⇒ same
    bytes.
    """
    rng = random.Random(seed)
    lines: list[str] = [*_NPM_PHASE, "$ cargo build --release --locked"]
    lines.extend(f"   Compiling {crate}" for crate in _CARGO_CRATES)
    lines.extend(_CARGO_WARNING)
    lines.extend(_PYTEST_HEADER)

    hour, minute, sec = 6, 41, 12
    for i in range(n_app_lines):
        sec += rng.randint(0, 2)
        if sec >= 60:
            sec -= 60
            minute += 1
        stamp = f"2026-07-03 {hour:02d}:{minute:02d}:{sec:02d},{rng.randint(0, 999):03d}"
        module = rng.choice(_APP_MODULES)
        took_ms = rng.randint(2, 480)
        lines.append(f"{stamp} INFO furl_ctx.{module} case_{i:03d} completed in {took_ms}ms")
        if i % 23 == 11:
            lines.append(
                f"{stamp} WARNING furl_ctx.{module} soft budget exceeded "
                f"({rng.randint(101, 240)}ms > 100ms), continuing"
            )
    lines.extend(_PYTEST_FAILURE)
    return "\n".join(lines)


MARKDOWN_DOC = """# Headroom

Headroom is a context compression engine for AI coding agents. It sits between
your agent and the model API, rewriting bulky tool output into a compact,
recoverable form before the tokens ever reach the context window. The engine
targets the long tail of agent transcripts: search results, build logs,
diffs, and file reads that pile up turn after turn and crowd out the
conversation itself.

## Why context compression

Agent transcripts grow monotonically. Every tool call appends output that the
model must re-read on every subsequent turn, and most of that output is never
looked at again. Compressing it once pays back on every later turn. The
engine keeps what the model is likely to need, offloads the rest to a
recoverable store, and leaves a retrieval pointer in place of the dropped
content so nothing is silently lost.

## Installation

Install from PyPI. The wheel bundles the Rust core, so no toolchain is
required. Python 3.10 or newer is supported on Linux, macOS, and Windows.

    pip install headroom
    python -c "import furl_ctx; print(furl_ctx.__version__)"

## Quick start

The one-call API compresses a chat-style message list in place. Pass your
messages and a model name; the result carries the compressed messages, token
counts before and after, and the list of transforms that fired.

    from furl_ctx import compress

    result = compress(messages, model="gpt-4o")
    print(result.tokens_before, "->", result.tokens_after)

## How it works

- A content router classifies every tool output: JSON arrays, search
  results, build logs, unified diffs, source code, or plain prose.
- Structured arrays go to a columnar crusher that renders a lossless
  schema-and-rows table when that is cheaper than the raw JSON.
- Search, log, and diff output goes to format-aware compressors that keep
  the high-signal lines, summaries, and hunks while eliding repetitive noise.
- Prose goes to an extractive summarizer that keeps the opening, the
  closing, and the highest-signal middle segments.
- Everything dropped is stored in a compress-cache-retrieve layer keyed by
  a content hash, and a marker line in the output tells the model how to
  retrieve it.

## Configuration

The defaults are tuned for coding agents and require no configuration. For
special deployments you can adjust the minimum token threshold below which
messages pass through untouched, disable compression of user messages, or
turn on strict lossless-only mode in which nothing is ever dropped. Each
knob is documented on the configuration dataclass with its tradeoffs.

## Guarantees

The engine never edits user or system messages by default, never reorders
messages, and never drops content without leaving a retrieval pointer. The
lossless columnar path is round-trip verified by a reference decoder in the
test suite. When a store write cannot complete, the engine serves the
original bytes rather than shipping a marker that could dangle.

## Benchmarks

The repository ships an honest benchmark suite over real captured tool
output. Numbers are reported separately for the lossless path and the lossy
recoverable path, and every dataset raw capture is committed for audit.
Compression on real search output reaches roughly ninety percent, logs
compress by about a third losslessly, and recall of a planted needle row
stays at one hundred percent when the recovery store is enabled.

## License

Headroom is released under the MIT license. Contributions are welcome; see
the contributing guide for the development workflow, and please run the
benchmark floor check before submitting a pull request that touches the
engine.
"""
