"""Provably-safe permission guard on the PreToolUse pipe (reviewer-guard).

CORE INVARIANT (total, provable): when the pipe is enabled, it rewrites a Bash
command ONLY IF there are ZERO readable Bash permission rules. If ANY Bash rule
of ANY kind exists — ``deny``, ``ask``, OR ``allow`` (blanket or scoped) across
enterprise managed + project + local + user settings — the hook PASSES THROUGH
ALL Bash: no rewrite, no per-verb analysis. This makes "never mask a deny/ask
rule" TOTAL: no command shape (a command-modifier wrapper Claude Code sees
through like ``env``/``sudo``/``flock``/``strace``/``ltrace``, a compound, an
absolute-path verb, or anything CC's closed-source resolver interprets) can be
masked, because when a rule exists NOTHING is rewritten. Unreadable/malformed
settings → doubt → passthrough too. Fail toward no-compression, never toward
masking a rule.

This REPLACES the earlier per-verb matcher + wrapper denylist (which reviewer-
guard proved could never be a complete boundary against CC's closed, version-
dependent see-through set). The contract is now STRICTLY SAFER — more commands
pass through, never fewer — so the tests that asserted the old per-verb
rewrite/passthrough splits are replaced, not weakened.

Unit tests feed the loader/predicate synthetic settings; acceptance tests run
the real hook as a subprocess against settings on disk with a hermetic HOME.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HOOKS = Path(__file__).resolve().parents[1] / "plugins" / "furl" / "hooks"
_PRETOOL = _HOOKS / "pretool_pipe.py"

_spec = importlib.util.spec_from_file_location("_furl_pretool_pipe_guard", _PRETOOL)
assert _spec is not None and _spec.loader is not None
_pretool_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pretool_mod)


def _write_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _deny(*rules: str) -> dict:
    return {"permissions": {"deny": list(rules)}}


def _ask(*rules: str) -> dict:
    return {"permissions": {"ask": list(rules)}}


def _allow(*rules: str) -> dict:
    return {"permissions": {"allow": list(rules)}}


# --- unit: rule loader (existence + doubt) ----------------------------------------


def test_loader_collects_bash_deny_ask_and_allow(tmp_path) -> None:
    """R2: deny, ask, AND allow Bash entries are all collected — an allow-list
    config is itself a restrictive posture. Other tools' rules (and BashOutput,
    which merely shares the prefix) are skipped."""
    path = tmp_path / "settings.json"
    _write_settings(
        path,
        {
            "permissions": {
                "deny": ["Bash(printf:*)", "WebFetch", "Read(/etc/*)"],
                "ask": ["Bash(curl:*)"],
                "allow": ["Bash(cat:*)", "BashOutput(x)"],
            }
        },
    )
    bodies, doubt = _pretool_mod._load_bash_rule_bodies((path,))
    assert doubt is False
    assert bodies == ["printf:*", "curl:*", "cat:*"]


def test_loader_recognizes_odd_but_valid_bash_shapes(tmp_path) -> None:
    """Refinement: every syntactically-odd-but-recognizable Bash rule counts as
    PRESENT — whitespace-padded, a space after the paren, an UNTERMINATED rule
    (no close paren), and the bare blanket ``Bash``. None is silently dropped."""
    path = tmp_path / "settings.json"
    _write_settings(
        path,
        {"permissions": {"deny": [" Bash(rm:*) ", "Bash( rm:*)", "Bash(rm:*", "Bash"]}},
    )
    bodies, doubt = _pretool_mod._load_bash_rule_bodies((path,))
    assert doubt is False
    assert len(bodies) == 4, "every recognizable Bash rule shape must be present"
    assert _pretool_mod._has_any_bash_rule(bodies) is True


def test_loader_bashoutput_is_not_a_bash_rule(tmp_path) -> None:
    """``BashOutput`` is a distinct tool (reads a background shell's output); it
    does NOT govern command execution, so it must not be read as a Bash rule.
    The ``Bash(`` open-paren check disambiguates it from ``Bash(...)``."""
    path = tmp_path / "settings.json"
    _write_settings(path, {"permissions": {"deny": ["BashOutput(x)", "BashOutputFoo"]}})
    bodies, doubt = _pretool_mod._load_bash_rule_bodies((path,))
    assert (bodies, doubt) == ([], False)
    assert _pretool_mod._has_any_bash_rule(bodies) is False


def test_loader_missing_file_is_not_doubt(tmp_path) -> None:
    bodies, doubt = _pretool_mod._load_bash_rule_bodies((tmp_path / "absent.json",))
    assert (bodies, doubt) == ([], False)


def test_loader_doubt_on_malformed_sources(tmp_path) -> None:
    """Anything that PREVENTS knowing the rules is doubt → passthrough: invalid
    JSON, a non-dict document, a non-dict permissions block, a non-list
    deny/ask/allow array, or a non-string entry."""
    cases = [
        "{not json",
        json.dumps(["not", "a", "dict"]),
        json.dumps({"permissions": "nope"}),
        json.dumps({"permissions": {"deny": "Bash(printf:*)"}}),
        json.dumps({"permissions": {"allow": [42]}}),
    ]
    for i, text in enumerate(cases):
        path = tmp_path / f"settings-{i}.json"
        path.write_text(text, encoding="utf-8")
        _bodies, doubt = _pretool_mod._load_bash_rule_bodies((path,))
        assert doubt is True, f"case {i} must raise doubt: {text!r}"


def test_loader_merges_all_settings_files(tmp_path) -> None:
    a = tmp_path / "a" / "settings.json"
    b = tmp_path / "b" / "settings.local.json"
    _write_settings(a, _deny("Bash(touch:*)"))
    _write_settings(b, _allow("Bash(curl:*)"))
    bodies, doubt = _pretool_mod._load_bash_rule_bodies((a, b))
    assert doubt is False
    assert sorted(str(x) for x in bodies) == ["curl:*", "touch:*"]


# --- unit: the existence predicate ------------------------------------------------


def test_has_any_bash_rule_true_for_scoped_and_blanket() -> None:
    assert _pretool_mod._has_any_bash_rule(["printf:*"]) is True
    # CRITICAL: a blanket/unterminated rule is a None body; the predicate uses
    # bool(bodies), not any(bodies) — any([None]) is False, bool([None]) is True.
    assert _pretool_mod._has_any_bash_rule([None]) is True
    assert _pretool_mod._has_any_bash_rule([None, "rm:*"]) is True


def test_has_any_bash_rule_false_only_for_empty() -> None:
    assert _pretool_mod._has_any_bash_rule([]) is False


# --- acceptance: the real hook subprocess against settings on disk ----------------


def _run_hook(
    command: str,
    tmp: Path,
    *,
    cwd_settings: dict | str | None = None,
    cwd_local_settings: dict | None = None,
    home_settings: dict | None = None,
    project_dir_settings: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run pretool_pipe.py hermetically: HOME, the payload cwd, and (when given)
    CLAUDE_PROJECT_DIR are fresh directories carrying exactly the settings each
    scenario specifies."""
    proj = tmp / "proj"
    home = tmp / "home"
    proj.mkdir(exist_ok=True)
    home.mkdir(exist_ok=True)
    if cwd_settings is not None:
        target = proj / ".claude" / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = cwd_settings if isinstance(cwd_settings, str) else json.dumps(cwd_settings)
        target.write_text(text, encoding="utf-8")
    if cwd_local_settings is not None:
        _write_settings(proj / ".claude" / "settings.local.json", cwd_local_settings)
    if home_settings is not None:
        _write_settings(home / ".claude" / "settings.json", home_settings)
    env = {"HOME": str(home), "FURL_PRETOOL_PIPE": "1", "PATH": "/usr/bin:/bin"}
    if project_dir_settings is not None:
        project_root = tmp / "project-root"
        _write_settings(project_root / ".claude" / "settings.json", project_dir_settings)
        env["CLAUDE_PROJECT_DIR"] = str(project_root)
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(proj)}
    return subprocess.run(
        [sys.executable, str(_PRETOOL)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


# Every command shape reviewer-guard raised, plus the classes the old per-verb
# matcher got wrong. Under the total invariant, a SINGLE unrelated deny rule
# makes ALL of them pass through — including the ones that match no rule
# (``zzz …``, ``/usr/bin/printf``) and the wrappers CC sees through that were
# NOT in the old 18-verb denylist (``flock``/``strace``/``ltrace``). The
# non-matching + un-listed-wrapper shapes REWROTE pre-redesign → RED proof.
_EVERY_COMMAND_SHAPE = (
    "printf x",  # simple
    "printf x | tee y",  # compound
    "env printf HELLO",  # listed wrapper
    "flock -n /tmp/l printf X",  # 3rd-class wrapper (not in old denylist)
    "strace printf X",  # 3rd-class wrapper
    "ltrace printf X",  # 3rd-class wrapper
    "/usr/bin/printf X",  # absolute-path verb (old code REWROTE)
    "zzz totally unrelated",  # matches no rule (old code REWROTE)
    "FOO=1 printf x",  # env-assignment prefix
)


@pytest.mark.parametrize("command", _EVERY_COMMAND_SHAPE)
def test_any_deny_rule_present_passes_through_every_shape(command, tmp_path) -> None:
    """The total invariant: a single UNRELATED deny (``Bash(rm:*)``) makes every
    command shape pass through, regardless of its verb — no per-verb matching."""
    proc = _run_hook(command, tmp_path, cwd_settings=_deny("Bash(rm:*)"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", f"any rule present → passthrough all Bash: {command!r}"


def test_ask_rule_present_passes_through(tmp_path) -> None:
    """An ask rule triggers passthrough exactly like a deny rule."""
    proc = _run_hook("cat bigfile", tmp_path, cwd_settings=_ask("Bash(curl:*)"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_allow_rule_present_passes_through(tmp_path) -> None:
    """R2: an allow rule triggers passthrough too (allow-list mode makes unlisted
    commands restricted). Pre-redesign, allow rules did not gate → this rewrote."""
    proc = _run_hook("cat bigfile", tmp_path, cwd_settings=_allow("Bash(cat:*)"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


@pytest.mark.parametrize("odd_rule", [" Bash(rm:*) ", "Bash( rm:*)", "Bash(rm:*", "Bash"])
def test_odd_but_recognizable_rule_shape_passes_through(odd_rule, tmp_path) -> None:
    """Refinement: whitespace-padded, space-after-paren, UNTERMINATED, and bare
    blanket Bash rules each count as PRESENT → passthrough, even for a command
    the rule would not obviously name."""
    proc = _run_hook("cat bigfile", tmp_path, cwd_settings=_deny(odd_rule))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", f"recognizable rule {odd_rule!r} must force passthrough"


@pytest.mark.parametrize("command", ["cat bigfile", "env printf HELLO", "printf x | tee y"])
def test_zero_permission_config_rewrites(command, tmp_path) -> None:
    """The savings case — the WHOLE point: with NO permission config at all, even
    wrapper/compound commands rewrite. Zero-config sessions keep their savings."""
    proc = _run_hook(command, tmp_path)  # no settings written anywhere
    assert proc.returncode == 0, proc.stderr
    assert "updatedInput" in proc.stdout, f"zero rules → must rewrite: {command!r}"


def test_empty_permission_arrays_are_zero_rules_rewrite(tmp_path) -> None:
    """Empty deny/ask/allow arrays are zero rules (no bodies) → rewrite."""
    settings = {"permissions": {"deny": [], "ask": [], "allow": []}}
    proc = _run_hook("cat bigfile", tmp_path, cwd_settings=settings)
    assert proc.returncode == 0, proc.stderr
    assert "updatedInput" in proc.stdout


def test_malformed_settings_is_doubt_passthrough(tmp_path) -> None:
    """Unreadable rules = unknowable rules → doubt → passthrough, even for an
    innocuous command."""
    proc = _run_hook("cat bigfile", tmp_path, cwd_settings="{definitely not json")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


# --- acceptance: scope completeness (a rule in ANY readable scope gates) ----------


def test_home_scope_rule_passes_through(tmp_path) -> None:
    proc = _run_hook("cat big", tmp_path, home_settings=_deny("Bash(printf:*)"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", "user-scope (~/.claude) rule must gate"


def test_claude_project_dir_scope_rule_passes_through(tmp_path) -> None:
    """CC loads project settings from the session's project root
    (CLAUDE_PROJECT_DIR); a rule there must gate even when the payload cwd is a
    subdirectory with no .claude of its own."""
    proc = _run_hook("cat big", tmp_path, project_dir_settings=_deny("Bash(printf:*)"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", "project-root (CLAUDE_PROJECT_DIR) rule must gate"


def test_local_settings_scope_rule_passes_through(tmp_path) -> None:
    proc = _run_hook("cat big", tmp_path, cwd_local_settings=_ask("Bash(curl:*)"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", "project-local settings.local.json rule must gate"


def test_guard_is_hermetic_zero_rules_rewrites() -> None:
    """Meta-pin: every acceptance test supplies its own HOME + cwd, so a
    developer's real ~/.claude rules can never decide these outcomes — a truly
    empty environment rewrites."""
    with tempfile.TemporaryDirectory() as tmp:
        proc = _run_hook("cat bigfile", Path(tmp))
        assert "updatedInput" in proc.stdout


# --- G2: enterprise managed-settings scope ----------------------------------------
# Paths verified at code.claude.com/docs/en/settings. The real system path is not
# writable in CI, so behavior is proven by (1) the platform-correct path, (2)
# inclusion in _settings_paths, (3) an in-process flow test with a monkeypatched
# managed path, and (4) drop-in-dir doubt.


def test_managed_settings_path_is_platform_correct() -> None:
    expected = {
        "darwin": "/Library/Application Support/ClaudeCode/managed-settings.json",
        "linux": "/etc/claude-code/managed-settings.json",
        "win32": r"C:\Program Files\ClaudeCode\managed-settings.json",
    }
    paths = _pretool_mod._managed_settings_paths()
    if sys.platform in expected:
        assert str(paths[0]) == expected[sys.platform]
    else:
        assert paths == []


def test_settings_paths_includes_managed_scope(tmp_path) -> None:
    paths = _pretool_mod._settings_paths(str(tmp_path))
    for managed in _pretool_mod._managed_settings_paths():
        assert managed in paths, f"managed scope missing from settings paths: {managed}"


def test_managed_rule_flows_into_the_decision(tmp_path, monkeypatch) -> None:
    """A rule that exists ONLY in the managed scope is loaded and makes
    ``_has_any_bash_rule`` True — end to end without writing a protected path."""
    managed = tmp_path / "managed-settings.json"
    _write_settings(managed, _deny("Bash(rm:*)"))
    monkeypatch.setattr(_pretool_mod, "_managed_settings_paths", lambda: [managed])
    bodies, doubt = _pretool_mod._load_bash_rule_bodies(_pretool_mod._settings_paths(str(tmp_path)))
    assert doubt is False
    assert _pretool_mod._has_any_bash_rule(bodies) is True


def test_managed_dropin_dir_unreadable_is_doubt(tmp_path) -> None:
    """A managed-settings.d drop-in directory that cannot be enumerated is
    returned AS the directory path, which reads as OSError in the loader →
    doubt → passthrough."""
    dropin = tmp_path / "ClaudeCode" / "managed-settings.d"
    dropin.mkdir(parents=True)
    _bodies, doubt = _pretool_mod._load_bash_rule_bodies((dropin,))
    assert doubt is True
