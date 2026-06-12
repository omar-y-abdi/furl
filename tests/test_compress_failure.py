from __future__ import annotations

import importlib

from headroom.compress import compress


class _FailingPipeline:
    def apply(self, **kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("boom")


def test_compress_returns_original_messages_when_pipeline_fails(monkeypatch) -> None:
    compress_module = importlib.import_module("headroom.compress")
    monkeypatch.setattr(compress_module, "_get_pipeline", lambda: _FailingPipeline())

    messages = [{"role": "user", "content": "hello world " * 100}]
    result = compress(messages, model="gpt-4o")

    # On pipeline failure the original messages pass through untouched and the
    # token accounting collapses to zero (no observability side effects after
    # the compression-only amputation).
    assert result.messages == messages
    assert result.tokens_before == 0
    assert result.tokens_after == 0
    assert result.tokens_saved == 0
    assert result.compression_ratio == 0.0
