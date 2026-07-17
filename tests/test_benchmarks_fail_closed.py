"""A2: the benchmark harness must FAIL CLOSED on a broken engine.

``compress()`` never raises — on an internal failure (classically a missing or
shadowed ``furl_ctx._core`` native extension when run from the repo root) it
returns the ORIGINAL messages with ``error`` set and ``tokens_after == 0``. The
metric math then reads that as 0.0% reduction / "lossless" / 100% retention, and
the harness would write a plausible-looking but entirely fictional BASELINE.md.
These pin that a fail-open ABORTS the run and writes nothing.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import pytest

import benchmarks.metrics as metrics
import benchmarks.run_bench as run_bench
from benchmarks.metrics import BenchmarkAbortedError, _abort_if_fail_open


@dataclass
class _FakeResult:
    error: str | None
    messages: list
    tokens_before: int = 0
    tokens_after: int = 0


def test_abort_if_fail_open_raises_on_error() -> None:
    with pytest.raises(BenchmarkAbortedError, match="fail-opened"):
        _abort_if_fail_open(
            "case@1", _FakeResult(error="No module named 'furl_ctx._core'", messages=[])
        )


def test_abort_if_fail_open_passes_on_clean_result() -> None:
    # No error → no raise (the happy path stays silent).
    _abort_if_fail_open("case@1", _FakeResult(error=None, messages=[]))


def test_main_aborts_and_writes_nothing_when_core_missing(tmp_path, monkeypatch) -> None:
    # Simulate the repo-root shadowing: furl_ctx._core not importable.
    monkeypatch.setitem(sys.modules, "furl_ctx._core", None)
    out = tmp_path / "out"
    rc = run_bench.main(["--out", str(out)])
    assert rc == 1
    # Nothing was written — no fictional baseline.
    assert not (out / "BASELINE.md").exists()
    assert not (out / "baseline_results.json").exists()


def test_main_aborts_and_writes_nothing_on_per_item_fail_open(tmp_path, monkeypatch) -> None:
    # _core imports fine, but a per-item compress() fail-opens → still abort,
    # still write nothing.
    def _fail_open(messages, *a, **k):
        return _FakeResult(error="simulated fail-open", messages=messages)

    monkeypatch.setattr(metrics, "compress", _fail_open)
    out = tmp_path / "out"
    rc = run_bench.main(["--out", str(out)])
    assert rc == 1
    assert not (out / "BASELINE.md").exists()
    assert not (out / "baseline_results.json").exists()
