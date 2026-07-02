"""COR-11 (onnx_coreml routing) + COR-12 (mid-batch KeyError) regressions.

COR-11: ``is_onnx = backend == "onnx"`` missed the CoreML loader's
``backend="onnx_coreml"`` (kompress_compressor.py:482,516), so a CoreML
model took the PyTorch branch → ``next(model.parameters())`` → AttributeError
on the ``_OnnxModel`` wrapper (which has no ``.parameters``). That error is
NOT in ``_MODEL_UNAVAILABLE_ERRORS``, so it propagated as a "bug" and
compression was effectively disabled for ``HEADROOM_KOMPRESS_BACKEND=coreml``.
Fix: ``backend.startswith("onnx")`` at all three sites (matching
``_model_device_type``'s existing intent).

COR-12: in the batched path, when a forward pass raises a model-unavailable
error the affected texts are popped from ``kept_ids_per_text``; a LATER
successful batch carrying the same text's remaining chunks did
``kept_ids_per_text[text_idx].add(...)`` on the popped key → KeyError,
propagating the HANDLED model-unavailable case as a "bug" (threshold path,
``target_ratio=None`` — the default). Fix: membership guard skips finalized
texts.
"""

from __future__ import annotations

import pytest

import headroom.transforms.kompress_compressor as kc
from headroom.cache.compression_store import reset_compression_store
from headroom.transforms.kompress_compressor import KompressCompressor, KompressConfig


class _IdMatrix:
    """Minimal [batch, seq] tensor stand-in (numpy not in this venv)."""

    def __init__(self, batch: int, seq_len: int) -> None:
        self.shape = (batch, seq_len)


@pytest.fixture(autouse=True)
def _isolate_store_and_cache():
    reset_compression_store()
    saved_cache = dict(kc._kompress_cache)
    kc._kompress_cache.clear()
    yield
    kc._kompress_cache.clear()
    kc._kompress_cache.update(saved_cache)
    reset_compression_store()


class _OneTokenPerWordEncoding:
    """Each input word maps to exactly one token (no truncation, no padding
    across a single-list call)."""

    def __init__(self, word_lists):
        max_len = max(len(w) for w in word_lists)
        self._batch = [list(range(len(wl))) + [None] * (max_len - len(wl)) for wl in word_lists]
        self._input_ids = _IdMatrix(len(word_lists), max_len)
        self._attention = _IdMatrix(len(word_lists), max_len)

    def __getitem__(self, key: str):
        return {"input_ids": self._input_ids, "attention_mask": self._attention}[key]

    def word_ids(self, batch_index: int = 0):
        return self._batch[batch_index]


class _StubTokenizer:
    def __call__(self, words, **kwargs):
        word_lists = words if words and isinstance(words[0], list) else [words]
        return _OneTokenPerWordEncoding(word_lists)


# ---------------------------------------------------------------------------
# COR-11 — a CoreML-backed (_OnnxModel-shaped) model must take the ONNX path.
# ---------------------------------------------------------------------------


class _OnnxShapedModel:
    """Mirrors ``_OnnxModel``'s interface: get_scores / get_keep_mask, and —
    crucially — NO ``.parameters`` method. The PyTorch branch calls
    ``next(model.parameters())``; if COR-11 misroutes an onnx_coreml backend
    there, this raises AttributeError (the real production failure)."""

    def __init__(self, keep_k: int) -> None:
        self._k = keep_k

    def get_keep_mask(self, input_ids, attention_mask, threshold: float = 0.5):
        seq_len = input_ids.shape[1]
        return [[i < self._k for i in range(seq_len)]]

    def get_scores(self, input_ids, attention_mask):
        batch, seq_len = input_ids.shape
        return [[1.0 if i < self._k else 0.0 for i in range(seq_len)] for _ in range(batch)]


def _content(n: int) -> str:
    return " ".join(f"word{i:02d}" for i in range(n))


def test_cor11_coreml_backend_takes_onnx_path_direct(monkeypatch) -> None:
    """compress(): an ``onnx_coreml`` backend must route to the ONNX branch,
    not PyTorch. Pre-fix ``== "onnx"`` sent the ``_OnnxModel`` wrapper to
    ``next(model.parameters())`` → AttributeError (compression disabled for
    HEADROOM_KOMPRESS_BACKEND=coreml).

    RED before the fix: AttributeError propagates out of compress().
    GREEN after: compression applies via the ONNX path."""
    model, tok = _OnnxShapedModel(keep_k=15), _StubTokenizer()
    monkeypatch.setattr(kc, "_load_kompress", lambda mid, dev: (model, tok, "onnx_coreml"))
    comp = KompressCompressor(KompressConfig(chunk_words=350, enable_ccr=False))

    content = _content(20)  # 15/20 kept → real compression
    result = comp.compress(content)

    # The ONNX path ran (no AttributeError) and compression applied.
    assert result.compression_ratio < 1.0, "coreml backend must actually compress"
    assert result.compressed != content
    # Only the first 15 words survive (get_keep_mask keeps i < 15).
    assert "word00" in result.compressed and "word14" in result.compressed
    assert "word15" not in result.compressed


def test_cor11_coreml_backend_takes_onnx_path_batched(monkeypatch) -> None:
    """compress_batch(): same onnx_coreml routing on the batched path (the
    second ``is_onnx`` site). Force the batched code (not the ONNX-CPU
    sequential fallback) so the batched branch is exercised."""
    model, tok = _OnnxShapedModel(keep_k=15), _StubTokenizer()
    monkeypatch.setattr(kc, "_load_kompress", lambda mid, dev: (model, tok, "onnx_coreml"))
    comp = KompressCompressor(KompressConfig(chunk_words=350, enable_ccr=False))
    monkeypatch.setattr(comp, "_should_use_sequential_fallback", lambda: False)

    content = _content(20)
    results = comp.compress_batch([content], target_ratio=[None])

    assert len(results) == 1
    result = results[0]
    assert result.compression_ratio < 1.0, "coreml backend must compress on the batched path"
    assert "word15" not in result.compressed


# ---------------------------------------------------------------------------
# COR-12 — mid-batch model-unavailable pop must not KeyError a later chunk.
# ---------------------------------------------------------------------------


class _FailFirstChunkModel:
    """Threshold-path model that raises OSError (a _MODEL_UNAVAILABLE error) on
    the FIRST forward pass and succeeds afterwards. With batch_size=1 and a
    2-chunk text, the first chunk's failure pops the text from
    ``kept_ids_per_text``; the second chunk's success then tries
    ``kept_ids_per_text[text_idx].add(...)`` — the popped key (COR-12)."""

    def __init__(self) -> None:
        self.calls = 0

    def get_keep_mask(self, input_ids, attention_mask, threshold: float = 0.5):
        seq_len = input_ids.shape[1]
        return [[True] * seq_len]

    def get_scores(self, input_ids, attention_mask):
        self.calls += 1
        if self.calls == 1:
            # Transient runtime failure on the first chunk's batch.
            raise OSError("INJECTED transient runtime failure on first chunk")
        batch, seq_len = input_ids.shape
        # Keep everything (score > default 0.5 threshold).
        return [[1.0] * seq_len for _ in range(batch)]


def test_cor12_midbatch_pop_then_later_chunk_no_keyerror(monkeypatch) -> None:
    """A 2-chunk threshold-path text whose FIRST chunk fails
    (model-unavailable) and SECOND chunk succeeds must NOT raise KeyError.

    RED before the fix: ``kept_ids_per_text[text_idx].add(...)`` on the popped
    key raises KeyError, which propagates out of compress_batch as a "bug".
    GREEN after: the membership guard skips the finalized (passthrough) text;
    the text comes back as passthrough, nothing crashes."""
    model, tok = _FailFirstChunkModel(), _StubTokenizer()
    monkeypatch.setattr(kc, "_load_kompress", lambda mid, dev: (model, tok, "onnx"))
    # chunk_words=10 → a 20-word text yields exactly 2 chunks.
    comp = KompressCompressor(KompressConfig(chunk_words=10, enable_ccr=False))
    monkeypatch.setattr(comp, "_should_use_sequential_fallback", lambda: False)

    content = _content(20)
    # batch_size=1 so each chunk is its own forward pass (chunk 1 fails,
    # chunk 2 succeeds against the SAME already-popped text_idx).
    results = comp.compress_batch([content], target_ratio=[None], batch_size=1)

    # No KeyError propagated; the text finalized to passthrough on the pop.
    assert len(results) == 1
    result = results[0]
    assert result.compressed == content, "the failed-then-popped text must be passthrough"
    assert result.compression_ratio == 1.0
    # The model was called for BOTH chunks (proving the second chunk ran the
    # threshold branch on the popped key — the exact COR-12 path).
    assert model.calls >= 2, "the later chunk's forward pass must have executed"
