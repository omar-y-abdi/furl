"""Regression test for #10: per-request runtime options dropped in worker threads.

apply() sets per-request options (force_kompress, target_ratio, kompress_model,
compression_policy) into self._tls (thread-local) on the MAIN thread. For a
multi-message apply() it compresses messages in a ThreadPoolExecutor; worker
threads have their OWN empty thread-local, so they read the DEFAULTS and silently
dropped the options — e.g. force_kompress=True was ignored for every worker
compression.

Fix: the main thread snapshots the options and passes them into _timed_compress,
which replays them into the worker's thread-local before compressing.

These tests FORCE the parallel worker branch (>=2 cache-miss messages, >=2
workers) and assert the work actually ran off-main-thread, then assert the
option propagated. Compression-neutral for default options (multiturn bench
unchanged).
"""
from __future__ import annotations

import threading

import pytest

from headroom.transforms.content_router import (
    CompressionStrategy,
    ContentRouter,
    ContentRouterConfig,
)
from headroom.tokenizers import get_tokenizer


@pytest.fixture
def _force_workers(monkeypatch):
    monkeypatch.setenv("HEADROOM_COMPRESS_WORKERS", "4")
    yield


def _two_noncode_messages() -> list[dict]:
    # Two DISTINCT, compressible, non-code messages (so detection would NOT pick
    # KOMPRESS on its own — forcing exposes the dropped option). Long enough to
    # be compression candidates, distinct so neither is a cache hit of the other.
    return [
        {"role": "tool", "content": "alpha " + "data point one " * 40},
        {"role": "tool", "content": "beta " + "different payload two " * 40},
    ]


def test_force_kompress_reaches_worker_threads(monkeypatch, _force_workers) -> None:
    router = ContentRouter(ContentRouterConfig())
    tokenizer = get_tokenizer("gpt-4o")
    main_ident = threading.get_ident()

    seen_force: list[bool] = []
    seen_idents: list[int] = []
    real_compress = ContentRouter.compress

    def spy_compress(self, content, **kwargs):
        # Record, IN THE EXECUTING THREAD, what force_kompress the router sees.
        seen_force.append(bool(getattr(self, "_runtime_force_kompress", False)))
        seen_idents.append(threading.get_ident())
        return real_compress(self, content, **kwargs)

    monkeypatch.setattr(ContentRouter, "compress", spy_compress)

    router.apply(
        _two_noncode_messages(),
        tokenizer,
        force_kompress=True,
    )

    # Proof the worker path actually ran (not the inline main-thread branch).
    assert seen_idents, "compress() was never called"
    assert any(i != main_ident for i in seen_idents), (
        "no compression ran off the main thread — the worker branch was not "
        "exercised, so this test would pass even with the bug present"
    )
    # #10: every worker compression must observe force_kompress=True.
    assert seen_force, "force_kompress was never observed"
    assert all(seen_force), (
        f"force_kompress dropped in a worker thread: observed {seen_force}"
    )


def test_default_options_unchanged_in_workers(monkeypatch, _force_workers) -> None:
    # No options set => workers must observe the defaults (False/None), i.e. the
    # snapshot of defaults is a no-op. Guards the no-degradation path.
    router = ContentRouter(ContentRouterConfig())
    tokenizer = get_tokenizer("gpt-4o")

    seen_force: list[bool] = []
    real_compress = ContentRouter.compress

    def spy_compress(self, content, **kwargs):
        seen_force.append(bool(getattr(self, "_runtime_force_kompress", False)))
        return real_compress(self, content, **kwargs)

    monkeypatch.setattr(ContentRouter, "compress", spy_compress)
    router.apply(_two_noncode_messages(), tokenizer)

    assert seen_force, "compress() was never called"
    assert not any(seen_force), "default force_kompress must remain False in workers"
