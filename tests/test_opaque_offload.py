"""T9 - opaque code-offload economics surfaced as a typed, spam-proof signal.

When ``compress()`` cannot structurally shrink content and instead offloads the
whole blob to the CCR store behind a marker (``compression_strategy ==
"ccr_offload"``), retrieving it back returns the entire payload, so the round
trip costs MORE than never compressing. Source code is the canonical trigger:
it does not compress structurally, so it reliably lands on this path.

The signal is a typed field on ``CompressResult`` (``opaque_offloads``) that the
caller reads at its own cadence. It is NOT a per-call stderr warning: Furl's
hooks spawn a fresh subprocess per tool call, so per-call logging explodes into
spam (see the #137 ledger row and the ANTHROPIC_O200K_PROXY_NOTE module comment
that removed the last stderr-warning attempt for exactly this reason).

Granular per-row offload (logs/search: ``smart_crusher_row_drop``) stays cheap
to retrieve and is NOT flagged.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from furl_ctx import CompressResult, OpaqueOffload, compress
from furl_ctx.cache.compression_store import reset_compression_store

BENCH_MODEL = "gpt-4o"


@pytest.fixture(autouse=True)
def _fresh_store():
    reset_compression_store()
    yield
    reset_compression_store()


def _code_snapshot_messages() -> list[dict[str, object]]:
    """The committed README ``code`` fixture: 7 real repo source files as one
    JSON tool output. This is the exact fixture the README "99%" claim is about,
    and it offloads opaquely (whole-blob) under the default config."""
    repo = Path(__file__).resolve().parents[1]
    snap = json.loads((repo / "benchmarks" / "data" / "code.raw.json").read_text(encoding="utf-8"))
    content = json.dumps(json.loads(snap["raw"]), ensure_ascii=False)
    return [
        {"role": "user", "content": "Review these source files for issues."},
        {"role": "tool", "content": content},
    ]


def _logs_payload(n: int = 150) -> str:
    """A repetitive log array that the SmartCrusher row-drops GRANULARLY
    (``smart_crusher_row_drop``) rather than offloading whole-blob."""
    rows = [
        {
            "ts": f"2026-07-20T10:{i // 60:02d}:{i % 60:02d}Z",
            "level": "INFO",
            "svc": "api",
            "msg": "request handled ok",
            "code": 200,
        }
        for i in range(n)
    ]
    return json.dumps(rows, ensure_ascii=False)


def test_opaque_code_offload_is_surfaced_in_typed_field():
    result = compress(_code_snapshot_messages(), model=BENCH_MODEL)

    assert isinstance(result, CompressResult)
    assert result.opaque_offloads, "an opaque code offload must be surfaced"
    assert all(isinstance(o, OpaqueOffload) for o in result.opaque_offloads)

    offload = result.opaque_offloads[0]
    # The recovery hash joins to the marker the caller sees.
    assert offload.hash in result.ccr_hashes
    # The marker replaced the bulk: far more moved to the store than kept inline.
    assert offload.offloaded_tokens > offload.preview_tokens > 0
    assert offload.offloaded_tokens > 10_000  # the ~41k-token code payload


def test_opaque_offload_reports_net_negative_round_trip():
    result = compress(_code_snapshot_messages(), model=BENCH_MODEL)
    offload = result.opaque_offloads[0]
    # Retrieving the whole blob back costs more than the offload saved.
    assert offload.net_negative_on_retrieval is True


def test_granular_row_offload_is_not_flagged_opaque():
    messages = [
        {"role": "user", "content": "Summarize these logs."},
        {"role": "tool", "content": _logs_payload()},
    ]
    result = compress(messages, model=BENCH_MODEL)
    # It compressed (offloaded rows granularly), but that is cheap to retrieve
    # per-row, so it is NOT an opaque whole-blob offload.
    assert result.ccr_hashes  # something was offloaded
    assert result.opaque_offloads == []


def test_small_content_has_no_opaque_offloads():
    messages = [{"role": "tool", "content": "a short tool output, nothing to offload"}]
    result = compress(messages, model=BENCH_MODEL)
    assert result.opaque_offloads == []


def test_opaque_offload_signal_is_structured_not_stderr(caplog):
    """Spam-proof: the signal lives in the typed field, never as a per-call
    WARNING log or a warnings-list string (the fresh-subprocess-per-call hook
    environment would turn either into stderr spam)."""
    with caplog.at_level(logging.WARNING, logger="furl_ctx.compress"):
        result = compress(_code_snapshot_messages(), model=BENCH_MODEL)

    assert result.opaque_offloads  # the signal is present...
    # ...but not as a stderr-logged warning, and not in the warnings list.
    assert not any("offload" in rec.getMessage().lower() for rec in caplog.records)
    assert not any("offload" in w.lower() for w in result.warnings)


def test_mcp_furl_compress_surfaces_opaque_offload(monkeypatch):
    """The MCP caller sees the same signal: a structured ``opaque_offloads``
    field in the response plus one honest line of copy about the round trip."""
    import importlib
    import types

    from furl_ctx.ccr.mcp_server import FurlMCPServer

    compress_mod = importlib.import_module("furl_ctx.compress")
    stubbed = CompressResult(
        messages=[{"role": "tool", "content": "[preview] <<ccr:abc123abc123>>"}],
        tokens_before=41025,
        tokens_after=1678,
        tokens_saved=39347,
        compression_ratio=39347 / 41025,
        transforms_applied=["router:ccr_offload:0.04"],
        opaque_offloads=[
            OpaqueOffload(
                hash="abc123abc123",
                tool_name="Bash",
                offloaded_tokens=41005,
                preview_tokens=1601,
                net_negative_on_retrieval=True,
            )
        ],
    )
    monkeypatch.setattr(compress_mod, "compress", lambda *a, **k: stubbed)

    stub_server = types.SimpleNamespace(
        _get_local_store=lambda: types.SimpleNamespace(
            store=lambda **k: "abc123abc123", exists=lambda h: True
        ),
        _stats=types.SimpleNamespace(record_compression=lambda *a, **k: None),
    )
    out = FurlMCPServer._compress_content(stub_server, "a big source-code blob")

    assert out["opaque_offloads"], "MCP response must surface the opaque offload"
    entry = out["opaque_offloads"][0]
    assert entry["hash"] == "abc123abc123"
    assert entry["offloaded_tokens"] == 41005
    assert entry["net_negative_on_retrieval"] is True
    assert "round trip" in out["note"].lower()
