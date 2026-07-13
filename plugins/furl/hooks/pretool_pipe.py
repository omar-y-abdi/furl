#!/usr/bin/env python3
"""Furl PreToolUse hook (ON BY DEFAULT — disable with FURL_PRETOOL_PIPE=0): the
real-savings compression path that does NOT depend on PostToolUse
``updatedToolOutput`` (silently dropped by Claude Code >=2.1.163 —
anthropics/claude-code#68951).

Unless disabled, this rewrites a ``Bash`` command so its STDOUT is piped through
the Furl compressor (``pipe_compress.py``) BEFORE it becomes the tool result —
so the model-visible output IS the compressed form, with the original stored
under a ``<<ccr:HASH>>`` marker (retrievable via ``furl_retrieve``), exactly
like the PostToolUse path.

SMART DEFAULT (v10, user-approved): the pipe runs UNLESS ``FURL_PRETOOL_PIPE``
is EXPLICITLY falsy — ``0``/``false``/``off``/``no``/``disabled``
(case-insensitive, whitespace-stripped). Unset, empty, and any other value —
including unknown junk — leave it ON ("on unless explicitly disabled", so a typo
never silently disables savings). Only ``Bash`` is touched.

Contract (PreToolUse):
  stdin  : JSON {tool_name, tool_input:{command, ...}, cwd, ...}
  stdout : to REWRITE, emit {"hookSpecificOutput": {"hookEventName":
           "PreToolUse", "updatedInput": {...tool_input, "command": <rewritten>}}}
  stdout empty + exit 0 : the original command runs unchanged.

The rewrite preserves the original command's EXIT CODE exactly. STDERR is never
captured and flows live — but because stdout is buffered for compression,
stderr/stdout interleaving is not preserved: in a merged view all stderr appears
before the (possibly compressed) stdout; ``cmd 2>&1`` merges both into the
compressed stream. Small outputs pass through raw (the compressor's own
threshold). FAIL-OPEN at the shell level twice over: a compressor that cannot
even start falls back to ``cat`` of the captured output, and if the stdout
tempfile cannot even be created the original command runs UNWRAPPED
(uncompressed, uncounted) — never a broken command.
FAIL-OPEN here too: any error emits nothing (exit 0) → original command runs.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

# The engine pin MUST match hooks.json's command pins (a test asserts this) so
# the compressor resolves the SAME furl-ctx the rest of the plugin uses.
_FURL_CTX_PIN = "furl-ctx[mcp]==1.2.0"

# Transparency marker: prepended to the rewritten command (visible in the
# transcript). Names the OPT-OUT since the pipe is on by default.
_PIPE_MARKER = "# furl-pipe (FURL_PRETOOL_PIPE=0 to disable)"

# Loop guard: the STABLE PREFIX of every marker version this plugin has ever
# emitted (old opt-in markers said "(FURL_PRETOOL_PIPE=1)"), so a command
# wrapped by ANY plugin version is never double-wrapped after an upgrade.
_PIPE_GUARD = "# furl-pipe"

_ENABLE_ENV = "FURL_PRETOOL_PIPE"

# The explicit opt-out set (S1 smart default). Shared semantics with the
# hooks.json shell gate — a parity test enumerates both.
_DISABLE_VALUES = frozenset({"0", "false", "off", "no", "disabled"})


def _pipe_disabled(raw: str | None) -> bool:
    """SMART DEFAULT (v10, user-approved): the pipe runs UNLESS explicitly
    disabled. True only for an explicit falsy value — 0/false/off/no/disabled,
    case-insensitive, whitespace-stripped. Unset (None), empty, and any
    unrecognized value return False (pipe ON): "on unless explicitly disabled",
    so a typo like ``FURL_PRETOOL_PIPE=fasle`` never silently disables savings.
    Must stay SEMANTICALLY IDENTICAL to the hooks.json shell gate
    (test_pretool_gate_parity_shell_and_python enumerates both)."""
    if raw is None:
        return False
    return raw.strip().lower() in _DISABLE_VALUES


def _passthrough() -> None:
    """Emit nothing and succeed: the original command runs unchanged."""
    sys.exit(0)


def _rewrite_command(original: str, project_dir: str, compressor: str) -> str:
    """Build the exit-code-preserving, fail-open pipe rewrite of *original*.

    Design:
      * ``if [ -n "$f" ] && : >"$f"`` — review F1 guard: PROBE that the tempfile
        is actually creatable/writable BEFORE any capture redirect touches the
        original. If the probe fails (mktemp unavailable AND the ``${TMPDIR}``
        fallback path unwritable), the ``else`` branch runs the ORIGINAL COMMAND
        with no redirect — inside a SUBSHELL whose ``)`` sits on its own line
        (review R1), exactly like the then branch: a bare interpolation would let
        an original ending in an ODD number of trailing backslashes line-continue
        into ``fi``, making the WHOLE script a parse error (rc 2, command never
        runs in either branch). The subshell is the branch's last statement, so
        stdout and the exit code still flow through exactly (fail-open: no
        compression rather than no command). Pre-F1, the redirect sat unprobed on
        the subshell and a tempfile failure meant the command NEVER RAN.
      * ``( <orig>\\n) >"$f"`` — a SUBSHELL captures only stdout to the tempfile;
        the closing ``)`` on its own line survives an *orig* that ends in a
        comment/``&``/heredoc. STDERR is never redirected — it flows live — but
        since stdout is buffered here and emitted at the end, stderr/stdout
        interleaving is NOT preserved: merged views show all stderr before the
        (possibly compressed) stdout; ``2>&1`` merges into the compressed stream.
      * ``__furl_ec=$?`` right after captures the original's exact exit code
        (the subshell's = its last command's), restored by the final ``exit``.
      * the compressor reads the tempfile; ``|| cat "$f"`` is the shell-level
        fail-open — if the compressor cannot even start (no ``uv``/python), the
        RAW captured output is emitted, never lost.
      * ``FURL_CCR_PROJECT_DIR`` + ``FURL_CCR_BACKEND=sqlite`` are baked so the
        compressor writes the original into the SAME durable per-project store
        the MCP server reads (a memory store would make the marker unretrievable).
    """
    qdir = shlex.quote(project_dir)
    qcomp = shlex.quote(compressor)
    return (
        f"{_PIPE_MARKER}\n"
        "__furl_f=$(mktemp 2>/dev/null || mktemp -t furlpipe 2>/dev/null"
        ' || printf %s "${TMPDIR:-/tmp}/furl-pipe.$$")\n'
        # NOTE: ``2>/dev/null`` BEFORE ``>"$f"`` — redirections process left to
        # right, so suppression must be in place before the probe redirect can
        # fail, or the failure message would leak to the live stderr stream.
        'if [ -n "$__furl_f" ] && : 2>/dev/null >"$__furl_f"; then\n'
        f"( {original}\n"
        ') >"$__furl_f"\n'
        "__furl_ec=$?\n"
        f"FURL_CCR_PROJECT_DIR={qdir} FURL_CCR_BACKEND=sqlite "
        f'uv run --no-project --with "{_FURL_CTX_PIN}" python3 {qcomp} <"$__furl_f"'
        ' || cat "$__furl_f"\n'
        'rm -f "$__furl_f"\n'
        "exit $__furl_ec\n"
        "else\n"
        'rm -f "$__furl_f" 2>/dev/null\n'
        f"( {original}\n"
        ")\n"
        "fi"
    )


def _project_dir(payload: dict) -> str:
    """Resolve the project dir the SAME way the PostToolUse hook and MCP server
    do (CLAUDE_PROJECT_DIR -> payload cwd -> getcwd), so the pipe's CCR writes
    land in the store the MCP server reads."""
    cwd = payload.get("cwd")
    return (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or (cwd if isinstance(cwd, str) and cwd.strip() else "")
        or os.getcwd()
    )


def main() -> None:
    # Opt-OUT gate FIRST (S1 smart default): an explicitly disabled pipe is a
    # byte-identical no-op — we never even parse stdin, zero added latency.
    if _pipe_disabled(os.environ.get(_ENABLE_ENV)):
        _passthrough()

    try:
        raw = sys.stdin.read()
    except Exception:
        _passthrough()
    if not raw.strip():
        _passthrough()
    try:
        payload = json.loads(raw)
    except Exception:
        _passthrough()
    if not isinstance(payload, dict):
        _passthrough()

    # Bash only (the matcher is Bash; double-check so a mis-scoped registration
    # can never rewrite another tool's input).
    if payload.get("tool_name") != "Bash":
        _passthrough()

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        _passthrough()
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        _passthrough()

    # Loop guard: never double-wrap a command we (any plugin version) rewrote —
    # matches the stable "# furl-pipe" prefix, not one marker spelling.
    if _PIPE_GUARD in command:
        _passthrough()

    compressor = str(Path(__file__).resolve().parent / "pipe_compress.py")
    rewritten = _rewrite_command(command, _project_dir(payload), compressor)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": {**tool_input, "command": rewritten},
        }
    }
    try:
        sys.stdout.write(json.dumps(output))
    except Exception:
        _passthrough()
    sys.exit(0)


if __name__ == "__main__":
    # Last-resort guard: no uncaught exception may reach the host — fail open to
    # the original command (emit nothing, exit 0).
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        sys.exit(0)
