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


def test_eval_recall_over_corpus_dir(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # A dir of two files: one compressible array, one plain doc. eval must
    # parse `--recall`, compress the corpus for the ratio, and run the needle-
    # recall trust gate.
    (tmp_path / "rows.json").write_text(_big_array(), encoding="utf-8")
    (tmp_path / "note.txt").write_text("plain prose, nothing to drop\n", encoding="utf-8")

    proc = _run(["eval", str(tmp_path), "--recall"])
    assert proc.returncode == 0, proc.stderr
    assert "files: 2" in proc.stdout
    # The corpus array compresses (ratio strictly between none and all).
    ratio = float(proc.stdout.split("corpus compression ratio:")[1].split("%")[0])
    assert 0.0 < ratio < 100.0
    # The needle-recall trust gate is 100% on a healthy engine (the naming arm
    # recalls its needle by construction); it drops if compression starts
    # silently losing content.
    recall = float(proc.stdout.split("trust gate):")[1].split("%")[0])
    assert recall == 100.0


def test_eval_requires_recall_flag(tmp_path) -> None:  # type: ignore[no-untyped-def]
    corpus = tmp_path / "rows.json"
    corpus.write_text(_big_array(), encoding="utf-8")
    proc = _run(["eval", str(corpus)])
    assert proc.returncode == 2  # argparse: missing required --recall
    assert "--recall" in proc.stderr
