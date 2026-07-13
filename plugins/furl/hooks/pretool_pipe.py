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
(case-insensitive, ALL whitespace removed). Unset, empty, and any other value —
including unknown junk — leave it ON ("on unless explicitly disabled", so a typo
never silently disables savings). Only ``Bash`` is touched.

CORE PROPERTY — PERMISSION-RULE SAFETY (provably-safe redesign, non-negotiable,
total): this hook MUST NEVER rewrite a command that Claude Code would subject to
a permissions **deny** or **ask** rule. Claude Code evaluates those rules against
the REWRITTEN command, and the furl-pipe wrapper no longer matches
``Bash(verb:*)`` patterns — so rewriting a governed command would silently
downgrade a hard deny to "ask" (normal mode) or trip the obfuscation classifier
(auto mode). The invariant is made TOTAL by a single predicate instead of
fragile per-verb matching: the hook rewrites a Bash command ONLY IF there are
ZERO readable Bash permission rules. If ANY Bash rule of ANY kind exists — deny,
ask, OR allow (see below), blanket or scoped — across enterprise managed
settings (the highest-precedence scope: the per-OS ``managed-settings.json`` +
its ``managed-settings.d`` fragments), project scope (``.claude/settings.json`` +
``.claude/settings.local.json`` under BOTH ``$CLAUDE_PROJECT_DIR`` and the
payload cwd), or user scope (``~/.claude/settings.json`` +
``~/.claude/settings.local.json``), it PASSES THROUGH ALL Bash: no rewrite, no
per-verb analysis. This makes "never mask a deny/ask rule" TOTAL — no command
shape (a command-modifier wrapper CC sees through like ``env``/``sudo``/``flock``
/``strace``, a compound, or anything CC's closed-source resolver interprets)
can be masked, because when a rule exists NOTHING is rewritten. ANY doubt
(unreadable or malformed settings) also PASSES THROUGH. Fail toward
no-compression, never toward masking a permission rule; no-savings is
acceptable, defeating a rule is not. WHY ``allow`` COUNTS: an allow-list config
makes UNLISTED commands restricted (ask/deny by default), so the mere presence
of allow rules is itself a maskable restrictive posture — including it keeps the
invariant total and is maximally conservative, while still meeting the
zero-config criterion (a fresh install has NO permissions config → rewrite →
savings). HONEST BLINDNESS: the hook still cannot see CLI flags
(``--permission-mode``, ``--disallowedTools``) or session-state (runtime-approved)
rules; users relying on CLI/session-level Bash restrictions should set
``FURL_PRETOOL_PIPE=0`` (documented in the plugin README).

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

# ASCII whitespace removal — the exact character class the shell gate's
# ``tr -d "[:space:]"`` deletes (POSIX locale), so both gates normalize
# identically even for values with INTERNAL whitespace (review-84 F1).
_WS_REMOVE = str.maketrans("", "", " \t\n\r\f\v")


def _pipe_disabled(raw: str | None) -> bool:
    """SMART DEFAULT (v10, user-approved): the pipe runs UNLESS explicitly
    disabled. True only for an explicit falsy value — 0/false/off/no/disabled,
    case-insensitive with ALL ASCII whitespace removed (so `` o f f `` is OFF,
    matching the shell gate's ``tr -d "[:space:]"`` exactly). Unset (None),
    empty, and any unrecognized value return False (pipe ON): "on unless
    explicitly disabled", so a typo like ``FURL_PRETOOL_PIPE=fasle`` never
    silently disables savings. SEMANTICALLY IDENTICAL to the hooks.json shell
    gate for every value (test_pretool_gate_parity_shell_and_python enumerates
    both, internal-whitespace cases included)."""
    if raw is None:
        return False
    return raw.translate(_WS_REMOVE).lower() in _DISABLE_VALUES


def _passthrough() -> None:
    """Emit nothing and succeed: the original command runs unchanged."""
    sys.exit(0)


# --- permission-rule guard (provably-safe redesign) -------------------------------
# The TOTAL invariant: rewrite a Bash command ONLY when ZERO readable Bash
# permission rules exist. No per-verb matching, no wrapper denylist, no compound
# analysis — existence of ANY rule is all we check, because when a rule exists
# NOTHING is rewritten, so no command shape can mask it. See the module docstring.

# Enterprise managed-settings.json locations, per OS. Paths VERIFIED against
# code.claude.com/docs/en/settings (reviewer-guard G2) — never guessed. An
# unrecognized platform maps to nothing (we do not invent a path). WSL shares
# the Linux path. Managed settings are the HIGHEST-precedence scope and cannot
# be overridden, so a Bash deny that lives only here must still gate the pipe.
_MANAGED_BASE_BY_PLATFORM = {
    "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
    "linux": Path("/etc/claude-code/managed-settings.json"),
    "win32": Path(r"C:\Program Files\ClaudeCode\managed-settings.json"),
}


def _managed_settings_paths() -> list[Path]:
    """Enterprise managed-settings sources for this platform: the per-OS
    ``managed-settings.json`` plus any ``managed-settings.d/*.json`` drop-in
    fragments alongside it. On an unrecognized platform, return nothing rather
    than GUESS a path. A drop-in directory that cannot be enumerated is returned
    AS the directory path — reading a directory raises ``OSError`` in the loader,
    which is surfaced as doubt → passthrough (never a silently missed policy)."""
    base = _MANAGED_BASE_BY_PLATFORM.get(sys.platform)
    if base is None:
        return []
    dropin = base.parent / "managed-settings.d"
    try:
        fragments = sorted(dropin.glob("*.json")) if dropin.is_dir() else []
    except OSError:
        return [base, dropin]
    return [base, *fragments]


def _settings_paths(cwd: str) -> tuple[Path, ...]:
    """The permission-rule sources this hook CAN see, in Claude Code order:
    enterprise managed settings, then project + project-local settings, then user
    scope. Project scope is read from BOTH ``CLAUDE_PROJECT_DIR`` (the session's
    project root, provided to every hook — where Claude Code actually loads
    project settings from) AND the payload cwd — they usually coincide, but when
    they differ (cwd in a subdirectory) the union is the conservative choice:
    more readable rules can only mean more passthrough, never a masked rule.
    Enterprise managed settings (the highest-precedence scope) ARE read
    (``_managed_settings_paths``). Still invisible here are CLI
    ``--permission-mode`` / ``--disallowedTools`` flags and session-level
    (runtime-approved) rules — the documented residual (set ``FURL_PRETOOL_PIPE=0``
    to disable the pipe if you restrict Bash only through those). Note
    ``~/.claude.json`` is intentionally NOT read: it carries no deny/ask rules
    (only ``allowedTools``), so a missed entry there is a savings nit, not a
    bypass."""
    project_dirs: list[Path] = []
    project_root = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project_root:
        project_dirs.append(Path(project_root))
    if Path(cwd) not in project_dirs:
        project_dirs.append(Path(cwd))
    scopes = [base / ".claude" for base in (*project_dirs, Path.home())]
    scoped = [scope / name for scope in scopes for name in ("settings.json", "settings.local.json")]
    return (*_managed_settings_paths(), *scoped)


def _bash_bodies_from_entries(entries: object) -> tuple[list[str | None], bool]:
    """Collect the Bash-governing rule bodies from one deny/ask/allow array.

    Returns ``(bodies, doubt)``: any Bash entry contributes a body (``None`` for
    a BLANKET bare ``Bash`` or an unparseable ``Bash(...``; the string body
    otherwise). Only EXISTENCE matters downstream, so the body content is now
    incidental — but it stays a faithful record of what was found. Rules for
    other tools (including ``BashOutput``, which merely shares the prefix) are
    irrelevant to a Bash rewrite and are skipped. Any shape we cannot read raises
    *doubt* instead of being guessed at."""
    bodies: list[str | None] = []
    if not isinstance(entries, list):
        return bodies, True
    doubt = False
    for entry in entries:
        if not isinstance(entry, str):
            doubt = True
            continue
        rule = entry.strip()
        # A recognizable Bash rule is EXACTLY ``Bash`` or starts with ``Bash(``.
        # The open paren disambiguates ``Bash(...)`` from the sibling tool
        # ``BashOutput`` (which does not govern command execution). Whitespace is
        # stripped first, so `` Bash(rm:*) `` and ``Bash( rm:*)`` both count. An
        # UNTERMINATED but recognizable rule (``Bash(rm:*`` — no close paren)
        # still counts as PRESENT (a ``None`` body) and is never silently
        # dropped: presence is what gates the rewrite, so a rule we can see but
        # not fully parse must still force passthrough.
        if rule == "Bash":
            bodies.append(None)
        elif rule.startswith("Bash("):
            bodies.append(rule[5:-1] if rule.endswith(")") else None)
    return bodies, doubt


def _load_bash_rule_bodies(paths: tuple[Path, ...]) -> tuple[list[str | None], bool]:
    """Union of every ``deny``/``ask``/``allow`` Bash rule body across *paths*.

    Precedence is irrelevant to a conservative union: a rule in ANY scope could
    gate the command, so all of them count. ``allow`` is included because an
    allow-list config makes UNLISTED commands restricted, so its presence is
    itself a maskable posture (see the module docstring). ``doubt`` is True when
    a source EXISTS but cannot be read or parsed (unreadable file, invalid JSON,
    wrong shapes) — the caller must pass through, because unknowable rules could
    contain a deny. A missing file is not doubt; it simply has no rules."""
    bodies: list[str | None] = []
    doubt = False
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError:
            doubt = True
            continue
        try:
            data = json.loads(text)
        except ValueError:
            doubt = True
            continue
        if not isinstance(data, dict):
            doubt = True
            continue
        permissions = data.get("permissions")
        if permissions is None:
            continue
        if not isinstance(permissions, dict):
            doubt = True
            continue
        for key in ("deny", "ask", "allow"):
            if key not in permissions:
                continue
            found, entry_doubt = _bash_bodies_from_entries(permissions[key])
            bodies.extend(found)
            doubt = doubt or entry_doubt
    return bodies, doubt


def _has_any_bash_rule(bodies: list[str | None]) -> bool:
    """The TOTAL invariant's predicate: True iff ANY readable Bash permission
    rule exists (deny/ask/allow, blanket or scoped). A rewrite happens ONLY when
    this is False (and there is no doubt) — no per-verb matching, because when a
    rule exists NOTHING is rewritten, so no command shape can mask it.

    Uses ``bool(bodies)`` (list non-empty), NOT ``any(bodies)``: a blanket or
    unterminated rule contributes a ``None`` body, and ``any([None])`` is False
    while ``bool([None])`` is True — a recognizable rule must count as present
    even when its body could not be parsed."""
    return bool(bodies)


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

    # SECURITY GUARD (provably-safe, total): rewrite ONLY when ZERO readable Bash
    # permission rules exist. If ANY Bash rule (deny/ask/allow) is present — or
    # settings are unreadable/malformed (doubt) — pass through so the original
    # command runs and CC's rules apply exactly as native. No per-verb analysis,
    # so no command shape can mask a rule.
    raw_cwd = payload.get("cwd")
    guard_cwd = raw_cwd if isinstance(raw_cwd, str) and raw_cwd.strip() else os.getcwd()
    bodies, doubt = _load_bash_rule_bodies(_settings_paths(guard_cwd))
    if doubt or _has_any_bash_rule(bodies):
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
