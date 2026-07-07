"""furl CLI: compress (stdin -> stdout), retrieve (miss), doctor."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _run(args: list[str], stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "furl_ctx.cli", *args],
        input=stdin,
        capture_output=True,
        text=True,
        env={**os.environ, "FURL_CCR_BACKEND": "memory"},
    )


def _big_array() -> str:
    return json.dumps([{"id": i, "status": "ok", "host": "w-01"} for i in range(400)])


def test_doctor_reports_ok() -> None:
    proc = _run(["doctor"])
    assert proc.returncode == 0
    assert "[OK] furl_ctx import" in proc.stdout
    assert "[OK] native _core" in proc.stdout


def test_compress_stdin_to_stdout_shrinks() -> None:
    payload = _big_array()
    proc = _run(["compress"], stdin=payload)
    assert proc.returncode == 0
    assert 0 < len(proc.stdout) < len(payload)


def test_compress_json_reports_token_savings() -> None:
    proc = _run(["compress", "--json"], stdin=_big_array())
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["tokens_after"] < out["tokens_before"]
    assert "compressed" in out and out["error"] is None


def test_retrieve_unknown_hash_exits_1() -> None:
    proc = _run(["retrieve", "0" * 24])
    assert proc.returncode == 1
    assert "not found" in proc.stderr
