"""Regression guard for the Furl plugin hooks manifest (plugins/furl/hooks/hooks.json).

Claude Code's plugin loader validates hooks.json against its hooks schema: event
handlers MUST be wrapped in a top-level ``"hooks"`` record keyed by event name.
Shipping the bare ``{"PostToolUse": [...]}`` shape (no wrapper) made the loader
reject the file with ``hooks: Invalid input: expected record, received undefined``
and silently disabled the hook. These tests pin the valid shape and the exact
runtime behavior (matcher, command, timeout) so it cannot recur.

Env contract: the manifest sets NO environment variables — neither a per-hook
``env`` object (the loader ignores the field) nor inline ``VAR=value`` assignments
in the command (``VAR=x cmd`` sets the child env unconditionally, which would
override a user's exported values such as ``FURL_CCR_BACKEND=memory``). The CCR
defaults (FURL_CCR_BACKEND=sqlite, FURL_CCR_TTL_SECONDS=86400) are owned by
compress_tool_output.py via ``os.environ.setdefault``, which honors user overrides.

Pure JSON/text checks — no furl_ctx import — so the guard runs even without the
built extension.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PLUGIN_HOOKS_DIR = Path(__file__).resolve().parents[1] / "plugins" / "furl" / "hooks"
_HOOKS_JSON = _PLUGIN_HOOKS_DIR / "hooks.json"
_HOOK_SCRIPT = _PLUGIN_HOOKS_DIR / "compress_tool_output.py"

# Only event Furl ships. The loader rejects unknown event keys ("Invalid key in
# record"), so keeping this pinned also guards against typo'd event names.
_EVENT = "PostToolUse"

# The exact command the plugin ships — byte-identical to the pre-schema-fix
# command; only the wrapper around it changed. Any edit here must be deliberate.
_EXPECTED_COMMAND = (
    'sh -lc \'uv run --no-project --with "furl-ctx[mcp]" '
    'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/compress_tool_output.py" || true\''
)

# Fields the schema does not honor where the old manifest wrongly placed them:
# the host silently ignores ``description``/``id`` at the matcher level and ``env``
# per command hook. They must not reappear.
_FORBIDDEN_MATCHER_KEYS = {"description", "id"}
_FORBIDDEN_HOOK_KEYS = {"env"}


def _load() -> dict[str, Any]:
    return json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))


def test_top_level_is_hooks_record() -> None:
    manifest = _load()
    # The wrapper the loader requires; the bare {"PostToolUse": ...} shape is the bug.
    assert set(manifest.keys()) == {"hooks"}
    assert "PostToolUse" not in manifest
    assert isinstance(manifest["hooks"], dict)


def test_events_are_known_and_arrays() -> None:
    events = _load()["hooks"]
    assert _EVENT in events
    for name, groups in events.items():
        assert name == _EVENT  # only PostToolUse is shipped
        assert isinstance(groups, list)
        assert groups


def test_matcher_groups_reject_forbidden_keys() -> None:
    for group in _load()["hooks"][_EVENT]:
        assert set(group.keys()) <= {"matcher", "hooks"}
        assert not (_FORBIDDEN_MATCHER_KEYS & set(group.keys()))
        assert isinstance(group["hooks"], list)
        assert group["hooks"]


def test_command_hooks_are_well_formed_without_env() -> None:
    for group in _load()["hooks"][_EVENT]:
        for hook in group["hooks"]:
            assert hook["type"] == "command"
            assert isinstance(hook["command"], str)
            assert hook["command"]
            assert not (_FORBIDDEN_HOOK_KEYS & set(hook.keys()))


def test_runtime_behavior_preserved() -> None:
    group = _load()["hooks"][_EVENT][0]
    assert group["matcher"] == "Bash|WebFetch|WebSearch|Task"
    hook = group["hooks"][0]
    assert hook["timeout"] == 30
    command = hook["command"]
    assert command == _EXPECTED_COMMAND
    # No inline env pins: `VAR=x cmd` would clobber a user's exported override
    # (e.g. FURL_CCR_BACKEND=memory). Defaults belong to the script's setdefault.
    assert "FURL_CCR" not in command
    # Still invokes the bundled hook script via the plugin-root placeholder.
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/compress_tool_output.py" in command


def test_env_defaults_owned_by_hook_script_setdefault() -> None:
    # The user-overridable defaults must stay in the script; the manifest carries
    # none. Together with test_runtime_behavior_preserved this pins the contract.
    src = _HOOK_SCRIPT.read_text(encoding="utf-8")
    assert 'os.environ.setdefault("FURL_CCR_BACKEND", "sqlite")' in src
    assert 'os.environ.setdefault("FURL_CCR_TTL_SECONDS", "86400")' in src
