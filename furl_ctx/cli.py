"""``furl`` — command-line interface. A thin argparse wrapper over the library.

    furl compress [FILE]   # FILE (or - / omitted for stdin) -> compressed stdout
    furl retrieve HASH     # print the original content for a CCR marker hash
    furl doctor            # check the install: native core, tokenizer, CCR store

Shell-native access to the same engine the library and MCP server use — for
pipelines (``psql … | furl compress``), CI log reduction, and offline evaluation
with no LLM harness.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _read_input(path: str) -> str:
    if path in ("-", ""):
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _cmd_compress(args: argparse.Namespace) -> int:
    from furl_ctx import compress

    text = _read_input(args.file)
    result = compress([{"role": "tool", "content": text}], model=args.model)
    compressed = result.messages[0]["content"] if result.messages else text
    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "compressed": compressed,
                    "tokens_before": result.tokens_before,
                    "tokens_after": result.tokens_after,
                    "compression_ratio": result.compression_ratio,
                    "ccr_hashes": result.ccr_hashes,
                    "error": result.error,
                },
                indent=2,
            )
            + "\n"
        )
    else:
        sys.stdout.write(compressed)
    return 0


def _cmd_retrieve(args: argparse.Namespace) -> int:
    from furl_ctx import retrieve

    original = retrieve(args.hash)
    if original is None:
        sys.stderr.write(
            f"furl: hash {args.hash} not found in the CCR store window "
            "(never stored, evicted, or expired)\n"
        )
        return 1
    sys.stdout.write(original)
    return 0


def _cmd_doctor(_args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []

    try:
        import furl_ctx

        checks.append(("furl_ctx import", True, getattr(furl_ctx, "__version__", "?")))
    except Exception as exc:  # pragma: no cover - import failure is the diagnostic
        checks.append(("furl_ctx import", False, str(exc)))

    try:
        import furl_ctx._core as core  # native extension — load-bearing

        checks.append(("native _core", True, os.path.basename(core.__file__)))
    except Exception as exc:
        checks.append(("native _core", False, f"{exc} — compression fails open to 0%"))

    try:
        import tiktoken  # noqa: F401

        checks.append(("tiktoken", True, "available"))
    except Exception as exc:
        checks.append(("tiktoken", False, f"{exc} — token counts fall back to estimation"))

    try:
        from furl_ctx.cache.compression_store import get_compression_store

        store = get_compression_store()
        checks.append(("CCR store", True, type(store._backend).__name__))
    except Exception as exc:
        checks.append(("CCR store", False, str(exc)))

    for name, passed, detail in checks:
        sys.stdout.write(f"[{'OK' if passed else 'FAIL'}] {name}: {detail}\n")
    return 0 if all(passed for _, passed, _ in checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="furl", description="Furl context-compression CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_compress = sub.add_parser("compress", help="compress FILE or stdin to stdout")
    p_compress.add_argument("file", nargs="?", default="-", help="input file, or - for stdin")
    p_compress.add_argument("--model", default="claude-sonnet-4-5-20250929")
    p_compress.add_argument(
        "--json", action="store_true", help="emit compressed text + stats as JSON"
    )
    p_compress.set_defaults(func=_cmd_compress)

    p_retrieve = sub.add_parser("retrieve", help="print the original content for a CCR hash")
    p_retrieve.add_argument("hash")
    p_retrieve.set_defaults(func=_cmd_retrieve)

    p_doctor = sub.add_parser("doctor", help="check the install (core, tokenizer, store)")
    p_doctor.set_defaults(func=_cmd_doctor)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
