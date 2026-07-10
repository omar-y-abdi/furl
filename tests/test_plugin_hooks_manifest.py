"""Regression guard for the Furl plugin hooks manifest (plugins/furl/hooks/hooks.json).

Claude Code's plugin loader validates hooks.json against its hooks schema: event
handlers MUST be wrapped in a top-level ``"hooks"`` record keyed by event name.
Shipping the bare ``{"PostToolUse": [...]}`` shape (no wrapper) made the loader
reject the file with ``hooks: Invalid input: expected record, received undefined``
and silently disabled the hook. These tests pin the valid shape and the exact
runtime behavior (matcher, command, inlined env vars, timeout) so it cannot recur.

Pure JSON — no furl_ctx import — so the guard runs even without the built extension.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_HOOKS_JSON = Path(__file__).resolve().parents[1] / "plugins" / "furl" / "hooks" / "hooks.json"

# Only event Furl ships. The loader rejects unknown event keys ("Invalid key in
# record"), so keeping this pinned also guards against typo'd event names.
_EVENT = "PostToolUse"

# Fields the schema does not honor where the old manifest wrongly placed them:
# the host silently ignores ``description``/``id`` at the matcher level and ``env``
# per command hook. They must not reappear — the two env vars are inlined into the
# command string instead, which is where they actually take effect.
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
    # env vars preserved verbatim, inlined into the shell command (no `env` block)
    assert "FURL_CCR_BACKEND=sqlite" in command
    assert "FURL_CCR_TTL_SECONDS=86400" in command
    # still invokes the bundled hook script via the plugin-root placeholder
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/compress_tool_output.py" in command
