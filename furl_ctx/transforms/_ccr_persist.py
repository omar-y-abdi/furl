"""Shared CCR persistence for the compressor shims (ARCH-5).

One implementation of the persist-or-veto step that the diff / log /
search / text / code-aware compressors previously carried as verbatim
private copies of ``_persist_to_python_ccr``. Five copies is how the
next store-contract change misses one; each compressor now keeps only a
thin ``_persist_to_python_ccr`` delegator (the test/monkeypatch seam)
around this single function.

Recoverability invariant (mirrors ``cross_message_dedup._persist_original``
and the fail-safe SmartCrusher gets by raising): the store write must
succeed BEFORE the CCR marker ships. On ``False`` the caller serves the
ORIGINAL uncompressed content (no marker), so a dropped hunk / line /
match / segment / body is never signalled-but-unrecoverable. The veto
behavior is pinned by ``tests/test_ccr_persist_failure_vetoes.py``.
"""

from __future__ import annotations

import logging
from typing import Any


def persist_to_python_ccr(
    original: str,
    compressed: str,
    cache_key: str,
    *,
    compression_strategy: str,
    logger: logging.Logger,
) -> bool:
    """Promote a compressor-emitted ``cache_key`` into the production Python
    ``CompressionStore``. Returns ``True`` on success, ``False`` on any
    failure (store import or store write) — the caller then vetoes to a
    passthrough result so the marker never ships dangling.

    Args:
        original: The FULL original content — what retrieval must recover.
        compressed: The compressed rendition (stored alongside for stats).
        cache_key: The exact hash embedded in the emitted marker. The
            Rust-backed compressors emit ``MD5(original)[:24]`` while
            ``store()`` defaults to ``SHA-256(original)[:24]``, so it is
            passed as ``explicit_hash`` — retrieving the marker's hash must
            find the entry.
        compression_strategy: Route attribution for the entry (a
            ``CompressionStrategy`` value, e.g. ``"diff"``), feeding the
            shape-keyed retrieval-feedback loop (Engine P2-13).
        logger: The CALLER's module logger, so failure logs keep their
            per-compressor attribution.

    The ``compression_store`` import stays lazy INSIDE this function —
    deliberately: content producers must not pull the cache package at
    module import time, and the test suite swaps
    ``sys.modules["furl_ctx.cache.compression_store"]`` per call.
    """
    try:
        from ..cache.compression_store import get_compression_store
    except ImportError as e:
        logger.error("CCR store import failed; cache_key %s won't persist: %s", cache_key, e)
        return False
    try:
        store: Any = get_compression_store()
        store.store(
            original,
            compressed,
            explicit_hash=cache_key,
            compression_strategy=compression_strategy,
        )
        return True
    except Exception as e:
        logger.error(
            "CCR store write failed; cache_key %s — serving original "
            "uncompressed (no dangling marker): %s",
            cache_key,
            e,
        )
        return False
