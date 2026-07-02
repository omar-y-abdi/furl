"""COR-29: ``KompressCompressor.apply()`` ignored ``frozen_message_count``.

The pipeline forwards ``frozen_message_count`` (the provider's prompt-cache
prefix length) to every transform; ``SmartCrusher.apply`` honors it, but
``KompressCompressor.apply`` silently discarded it and would compress
messages INSIDE the frozen prefix — rewriting cached prefix bytes and
breaking prompt-cache prefix ordering. Latent in production (routing goes
via ContentRouter) but Kompress is a public ``Transform``.

Also: ``tokens_before``/``tokens_after`` were computed with
``str(m.get("content", ""))`` which stringifies Anthropic-style block-list
content into its Python repr — counting tokens that do not exist. Fix:
count string content only, at both sites.
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


class _OneTokenPerWordEncoding:
    def __init__(self, word_lists):
        max_len = max(len(w) for w in word_lists)
        self._batch = [list(range(len(wl))) + [None] * (max_len - len(wl)) for wl in word_lists]
        self._ids = _IdMatrix(len(word_lists), max_len)

    def __getitem__(self, key: str) -> _IdMatrix:
        return {"input_ids": self._ids, "attention_mask": self._ids}[key]

    def word_ids(self, batch_index: int = 0):
        return self._batch[batch_index]


class _StubTokenizer:
    def __call__(self, words, **kwargs) -> _OneTokenPerWordEncoding:
        word_lists = words if words and isinstance(words[0], list) else [words]
        return _OneTokenPerWordEncoding(word_lists)


class _KeepFirstKModel:
    """Keeps the first k words of any chunk: 20-word content -> ratio 0.5,
    comfortably under apply()'s 0.9 gate so compression is applied."""

    def __init__(self, k: int) -> None:
        self._k = k

    def get_keep_mask(self, input_ids, attention_mask, threshold: float = 0.5):
        seq_len = input_ids.shape[1]
        return [[i < self._k for i in range(seq_len)]]

    def get_scores(self, input_ids, attention_mask):
        batch, seq_len = input_ids.shape
        return [[1.0 if i < self._k else 0.0 for i in range(seq_len)] for _ in range(batch)]


class _WordCountTokenizer:
    """Duck-typed headroom Tokenizer: 1 whitespace word = 1 token."""

    def count_text(self, text: str) -> int:
        return len(text.split())


def _comp(monkeypatch) -> KompressCompressor:
    model, tok = _KeepFirstKModel(k=10), _StubTokenizer()
    monkeypatch.setattr(kc, "_load_kompress", lambda mid, dev: (model, tok, "onnx"))
    return KompressCompressor(KompressConfig(chunk_words=350, enable_ccr=False))


_TOOL_TEXT = " ".join(f"word{i:02d}" for i in range(20))


def _tool_message() -> dict:
    return {"role": "tool", "content": _TOOL_TEXT}


def test_apply_skips_frozen_prefix(monkeypatch) -> None:
    """Messages inside the frozen prefix must pass through untouched even
    when they are compressible; messages after it compress normally."""
    comp = _comp(monkeypatch)
    messages = [_tool_message(), _tool_message()]

    result = comp.apply(messages, _WordCountTokenizer(), frozen_message_count=1)

    assert result.messages[0]["content"] == _TOOL_TEXT, (
        "frozen message was rewritten — prompt-cache prefix broken"
    )
    assert result.messages[1]["content"] != _TOOL_TEXT, "unfrozen message must compress"
    assert result.transforms_applied == ["kompress:tool:0.50"]


def test_apply_default_compresses_all(monkeypatch) -> None:
    """Without the kwarg (default 0) every eligible message compresses —
    the freeze must not over-apply."""
    comp = _comp(monkeypatch)
    messages = [_tool_message(), _tool_message()]

    result = comp.apply(messages, _WordCountTokenizer())

    assert result.messages[0]["content"] != _TOOL_TEXT
    assert result.messages[1]["content"] != _TOOL_TEXT
    assert result.transforms_applied == ["kompress:tool:0.50", "kompress:tool:0.50"]


def test_apply_fully_frozen_is_noop(monkeypatch) -> None:
    comp = _comp(monkeypatch)
    messages = [_tool_message(), _tool_message()]

    result = comp.apply(messages, _WordCountTokenizer(), frozen_message_count=2)

    assert result.messages[0]["content"] == _TOOL_TEXT
    assert result.messages[1]["content"] == _TOOL_TEXT
    assert result.transforms_applied == ["kompress:noop"]
    assert result.tokens_before == result.tokens_after == 40


def test_apply_token_counts_ignore_block_list_content(monkeypatch) -> None:
    """Block-list (Anthropic-style) content must contribute 0 to the token
    counts — pre-fix ``str(blocks)`` counted the Python repr of the list."""
    comp = _comp(monkeypatch)
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hello block world"}]},
        _tool_message(),
    ]

    result = comp.apply(messages, _WordCountTokenizer())

    # Only the tool message's 20-word string counts before...
    assert result.tokens_before == 20, (
        f"block-list content must not be counted; tokens_before={result.tokens_before}"
    )
    # ...and only its 10-word compressed string counts after.
    assert result.messages[1]["content"] == " ".join(f"word{i:02d}" for i in range(10))
    assert result.tokens_after == 10, (
        f"block-list content must not be counted; tokens_after={result.tokens_after}"
    )
