"""End-to-end digit-fidelity pins for the compression preview.

A payments-style log whose lines carry zero-padded ``HH:MM:SS`` timestamps
is misread by the search compressor's grep parser as ``file:line:content``
(the ``:MM:`` minute field becomes the "line number"). The renderer used to
emit the *parsed* ``u64`` line number, stripping the zero pad, so a retained
example line the agent reads showed ``2026-07-11T13:0:00`` for an input of
``2026-07-11T13:00:00`` — a silent one-digit corruption exactly where a user
would eye-check the "100% information retention" claim.

Retrieval (``furl_retrieve``) was always byte-exact; only the inline preview
corrupted. These tests drive the real ``compress()`` path the MCP
``furl_compress`` tool uses and assert every retained preview line is a
byte-exact substring of the input.
"""

from __future__ import annotations

from furl_ctx.compress import compress

MODEL = "claude-sonnet-4-5-20250929"


def _compress_text(content: str) -> str:
    """Compress ``content`` exactly as the MCP furl_compress tool does."""
    result = compress([{"role": "tool", "content": content}], model=MODEL)
    assert result.error is None, result.error
    out = result.messages[0]["content"]
    if isinstance(out, list):
        out = "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in out
        )
    return out


def _assert_preview_lines_byte_exact(content: str, compressed: str) -> None:
    """Every rendered match line (not a ``[...]`` summary / retrieval marker)
    must appear verbatim in the input."""
    for line in compressed.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("[") or "Retrieve more:" in line:
            continue
        assert line in content, f"preview line not byte-exact in input:\n{line!r}"


def test_leading_zero_minutes_survive_in_preview() -> None:
    content = "\n".join(
        f"2026-07-11T13:{i % 10:02d}:00 INFO payment id={i:04d} amount={i % 8:03d}.50 status=ok"
        for i in range(60)
    )
    out = _compress_text(content)

    # The exact corruption the bug produced must be gone...
    assert "13:0:00" not in out, out
    # ...and the zero-padded minute must survive verbatim.
    assert "2026-07-11T13:00:00" in out, out
    _assert_preview_lines_byte_exact(content, out)


def test_zero_padded_ids_and_amounts_survive_in_preview() -> None:
    # Grep-shaped lines whose line-number token AND content tail are both
    # zero-padded (ids, amounts, hex).
    content = "\n".join(
        f"svc:{i:04d}:charge acct=00{i:03d} amount={i % 9:03d}.0{i % 10} ref=0x{i:04x} status=ok"
        for i in range(60)
    )
    out = _compress_text(content)

    # A padded id from the first (always-kept) line rides through verbatim.
    assert "svc:0000:charge acct=00000" in out, out
    _assert_preview_lines_byte_exact(content, out)
