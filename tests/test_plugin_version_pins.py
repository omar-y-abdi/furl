"""Version-consistency guards across Furl's distribution surfaces.

Two independent invariants, each enforced here so a drifting version fails CI — and,
in particular, fails the release-please release PR that bumps ``pyproject.toml`` until
the embedded command pins are synced. release-please has **no updater that can rewrite
a version embedded inside a shell-command string** (the ``json`` updater does
full-value replacement at a JSONPath; the ``generic`` updater needs inline
``x-release-please-version`` comments, which strict JSON cannot carry), so this test is
the backstop that keeps the pins honest. See CONTRIBUTING.md "Releasing / version
bumps".

LIBRARY version (``pyproject.toml`` ``project.version``): the ``furl-ctx[mcp]==X.Y.Z``
pins in the PostToolUse hook command (``hooks/hooks.json``) and the MCP server command
(``.mcp.json``) MUST equal it, so ``uv run`` fetches a deterministic wheel instead of
whatever stale resolution its cache happens to hold.

PLUGIN version (``plugin.json`` ``version``): the marketplace metadata + entry
versions, the skill frontmatter, and the baked SessionStart status-line version MUST
all equal it, because the plugin cache is version-keyed and the status line advertises
the running plugin build.

Pure stdlib (json, re, tomllib) — no furl_ctx import — so the guard runs even without
the built extension.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import tomllib

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_PLUGIN_DIR = _ROOT / "plugins" / "furl"
_HOOKS_JSON = _PLUGIN_DIR / "hooks" / "hooks.json"
_MCP_JSON = _PLUGIN_DIR / ".mcp.json"
_PLUGIN_JSON = _PLUGIN_DIR / ".claude-plugin" / "plugin.json"
_SKILL_MD = _PLUGIN_DIR / "skills" / "furl" / "SKILL.md"
_MARKETPLACE_JSON = _ROOT / ".claude-plugin" / "marketplace.json"

_SEMVER = r"\d+\.\d+\.\d+"
_PIN_RE = re.compile(r"furl-ctx\[mcp\]==(" + _SEMVER + r")")
_STATUS_VERSION_RE = re.compile(r"furl (" + _SEMVER + r") active")
_FRONTMATTER_VERSION_RE = re.compile(r"^version:\s*(" + _SEMVER + r")\s*$", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _pyproject_version() -> str:
    return str(tomllib.loads(_read(_PYPROJECT))["project"]["version"])


def _plugin_version() -> str:
    return str(json.loads(_read(_PLUGIN_JSON))["version"])


def _hook_command() -> str:
    hooks = json.loads(_read(_HOOKS_JSON))["hooks"]
    return str(hooks["PostToolUse"][0]["hooks"][0]["command"])


def _mcp_command() -> str:
    return " ".join(json.loads(_read(_MCP_JSON))["mcpServers"]["furl"]["args"])


def _session_start_command() -> str:
    hooks = json.loads(_read(_HOOKS_JSON))["hooks"]
    return str(hooks["SessionStart"][0]["hooks"][0]["command"])


def _extract(pattern: re.Pattern[str], text: str, label: str) -> str:
    match = pattern.search(text)
    assert match is not None, f"no {label} found in: {text!r}"
    return match.group(1)


# --- LIBRARY version: both command pins == pyproject ---


def test_hook_pin_matches_pyproject_version() -> None:
    assert _extract(_PIN_RE, _hook_command(), "furl-ctx[mcp] pin") == _pyproject_version()


def test_mcp_pin_matches_pyproject_version() -> None:
    assert _extract(_PIN_RE, _mcp_command(), "furl-ctx[mcp] pin") == _pyproject_version()


# --- PLUGIN version: marketplace + skill + status line == plugin.json ---


def test_marketplace_versions_match_plugin_version() -> None:
    market = json.loads(_read(_MARKETPLACE_JSON))
    plugin_version = _plugin_version()
    assert market["metadata"]["version"] == plugin_version
    entries = market["plugins"]
    assert len(entries) == 1
    assert entries[0]["version"] == plugin_version


def test_skill_frontmatter_matches_plugin_version() -> None:
    version = _extract(_FRONTMATTER_VERSION_RE, _read(_SKILL_MD), "skill frontmatter version")
    assert version == _plugin_version()


def test_session_start_status_line_version_matches_plugin_version() -> None:
    version = _extract(_STATUS_VERSION_RE, _session_start_command(), "status-line version")
    assert version == _plugin_version()
