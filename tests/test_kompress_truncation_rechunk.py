"""COR-22: tokenizer truncation silently deletes unscored tail words.

``chunk_words=350`` counts whitespace words, but the model scores at most
512 tokens per forward pass (``_MODEL_MAX_TOKENS``). Prose at ~1.3-1.5
tokens/word usually fits; code, URLs, or JSON routinely exceed it. With
``truncation=True`` the tokenizer silently drops the tail tokens — those
words get no ``word_ids`` entry, so no score, and were therefore ALWAYS
deleted regardless of importance: systematic positional deletion invisible
to both the score threshold and the ``target_ratio`` top-k.

Fix: detect truncation (sequence hit the ceiling AND word_ids coverage
stops short of the chunk) and re-chunk from the first unscored word so
every word is scored. Applies to both the direct path (``compress``) and
the batched path (``compress_batch``).

The fakes model the failure exactly: N tokens per word, rows truncated at
the ``max_length`` kwarg, batch rows padded with None — like a real HF
fast tokenizer. The keep-everything model makes deletion unambiguous: any
word missing from the output was never scored.
"""

from __future__ import annotations

import pytest

import headroom.transforms.kompress_compressor as kc
from headroom.cache.compression_store import reset_compression_store
from headroom.transforms.kompress_compressor import KompressCompressor, KompressConfig


@pytest.fixture(autouse=True)
def _isolate():
    reset_compression_store()
    saved = dict(kc._kompress_cache)
    kc._kompress_cache.clear()
    yield
    kc._kompress_cache.clear()
    kc._kompress_cache.update(saved)
    reset_compression_store()


class _IdMatrix:
    def __init__(self, batch: int, seq_len: int) -> None:
        self.shape = (batch, seq_len)


class _Encoding:
    """Batch of word_ids rows, padded with None to the longest row."""

    def __init__(self, rows: list[list[int | None]]) -> None:
        max_len = max(len(r) for r in rows)
        self._batch = [r + [None] * (max_len - len(r)) for r in rows]
        self._ids = _IdMatrix(len(rows), max_len)

    def __getitem__(self, key: str) -> _IdMatrix:
        return {"input_ids": self._ids, "attention_mask": self._ids}[key]

    def word_ids(self, batch_index: int = 0) -> list[int | None]:
        return self._batch[batch_index]


class _MultiTokenTokenizer:
    """`tokens_per_word` tokens per word, truncated at the max_length kwarg.

    Mirrors the real failure shape: a 300-word chunk at 2 tokens/word is 600
    tokens, truncated to 512 — words past index 255 get no word_ids.
    ``overrides`` maps a specific word to its own token count (giant
    URL/base64 blobs).
    """

    def __init__(self, tokens_per_word: int = 2, overrides: dict[str, int] | None = None) -> None:
        self._tpw = tokens_per_word
        self._overrides = overrides or {}
        self.calls = 0

    def __call__(self, words, **kwargs) -> _Encoding:
        self.calls += 1
        max_length = kwargs.get("max_length", 512)
        truncation = kwargs.get("truncation", False)
        word_lists = words if words and isinstance(words[0], list) else [words]
        rows: list[list[int | None]] = []
        for wl in word_lists:
            ids: list[int | None] = []
            for wid, word in enumerate(wl):
                ids.extend([wid] * self._overrides.get(word, self._tpw))
            rows.append(ids[:max_length] if truncation else ids)
        return _Encoding(rows)


class _KeepAllModel:
    """Keeps/max-scores every token it sees: a word missing from the output
    can only mean the model never scored it (the COR-22 deletion)."""

    def get_keep_mask(self, input_ids, attention_mask, threshold: float = 0.5):
        batch, seq_len = input_ids.shape
        return [[True] * seq_len for _ in range(batch)]

    def get_scores(self, input_ids, attention_mask):
        batch, seq_len = input_ids.shape
        return [[1.0] * seq_len for _ in range(batch)]


def _comp(monkeypatch, tokenizer: _MultiTokenTokenizer) -> KompressCompressor:
    monkeypatch.setattr(kc, "_load_kompress", lambda mid, dev: (_KeepAllModel(), tokenizer, "onnx"))
    return KompressCompressor(KompressConfig(chunk_words=350, enable_ccr=False))


_CONTENT_300 = " ".join(f"w{i:03d}" for i in range(300))


def test_direct_threshold_path_scores_all_words_past_ceiling(monkeypatch) -> None:
    """300 words x 2 tokens = 600 tokens > 512: pre-fix, words 256..299 got
    no score and were deleted even though the model keeps EVERYTHING.
    Post-fix the unscored tail is re-chunked and scored -> all 300 kept."""
    comp = _comp(monkeypatch, _MultiTokenTokenizer(tokens_per_word=2))
    result = comp.compress(_CONTENT_300)
    assert result.compressed_tokens == 300, (
        f"keep-all model must keep all 300 words; got {result.compressed_tokens} "
        "(truncated tail deleted unscored)"
    )
    assert result.compressed == _CONTENT_300


def test_direct_ratio_path_topk_over_all_words(monkeypatch) -> None:
    """target_ratio top-k must count ALL words, not just the untruncated
    prefix: round(300 * 0.5) = 150, not round(256 * 0.5) = 128."""
    comp = _comp(monkeypatch, _MultiTokenTokenizer(tokens_per_word=2))
    result = comp.compress(_CONTENT_300, target_ratio=0.5)
    assert result.compressed_tokens == 150, (
        f"expected round(300*0.5)=150 kept, got {result.compressed_tokens}"
    )


def test_giant_single_word_makes_progress(monkeypatch) -> None:
    """A single word tokenizing past the ceiling (URL/base64 blob) is consumed
    with its partial score — re-chunking must not loop on it, and the words
    after it must still be scored (pre-fix they were deleted unscored)."""
    tok = _MultiTokenTokenizer(tokens_per_word=2, overrides={"MONSTER": 600})
    comp = _comp(monkeypatch, tok)
    content = "MONSTER " + " ".join(f"w{i}" for i in range(11))
    result = comp.compress(content)
    assert result.compressed_tokens == 12, (
        f"all 12 words must be scored and kept; got {result.compressed_tokens}"
    )


def test_exact_fit_does_not_rechunk(monkeypatch) -> None:
    """256 words x 2 tokens = exactly 512: sequence hits the ceiling but
    coverage is complete — no re-chunk, a single tokenizer pass."""
    tok = _MultiTokenTokenizer(tokens_per_word=2)
    comp = _comp(monkeypatch, tok)
    content = " ".join(f"w{i:03d}" for i in range(256))
    result = comp.compress(content)
    assert result.compressed_tokens == 256
    assert tok.calls == 1, f"exact-fit chunk must not re-chunk; {tok.calls} tokenizer calls"


def test_batch_threshold_path_scores_all_words_past_ceiling(monkeypatch) -> None:
    """Batched path: the truncated text is re-chunked; the short text padded
    to the same 512-wide batch (complete coverage) must NOT be re-chunked."""
    tok = _MultiTokenTokenizer(tokens_per_word=2)
    comp = _comp(monkeypatch, tok)
    monkeypatch.setattr(comp, "_should_use_sequential_fallback", lambda: False)
    short = " ".join(f"s{i:02d}" for i in range(20))
    results = comp.compress_batch([_CONTENT_300, short], target_ratio=[None, None])
    assert len(results) == 2
    assert results[0].compressed_tokens == 300, (
        f"keep-all model must keep all 300 words; got {results[0].compressed_tokens}"
    )
    assert results[1].compressed_tokens == 20
    assert results[1].compressed == short


def test_batch_ratio_path_topk_over_all_words(monkeypatch) -> None:
    """Batched target_ratio top-k counts ALL words after re-chunking."""
    tok = _MultiTokenTokenizer(tokens_per_word=2)
    comp = _comp(monkeypatch, tok)
    monkeypatch.setattr(comp, "_should_use_sequential_fallback", lambda: False)
    results = comp.compress_batch([_CONTENT_300], target_ratio=[0.5])
    assert len(results) == 1
    assert results[0].compressed_tokens == 150, (
        f"expected round(300*0.5)=150 kept, got {results[0].compressed_tokens}"
    )
