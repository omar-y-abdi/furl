"""PERF-13 / API-8: version machinery is lazy, subprocess-free, and slim.

``import furl_ctx`` used to execute ``furl_ctx.release_version`` (310 LOC of
CI release tooling shipping inside the user wheel) and spawn ``git tag`` +
``git log`` subprocesses (~90 ms measured) in any checkout — every test
collection and every embedding process paid it. Pins:

* importing ``furl_ctx`` AND resolving ``__version__`` spawn NO subprocess
  (verified in a hermetic child interpreter with a spawn spy installed);
* ``__version__`` still resolves for every reader — module attribute,
  ``furl_ctx._version.get_version()``, and the ``importlib.metadata``
  fallback contract (``"unknown"`` when the distribution is missing);
* ``furl_ctx.release_version`` no longer exists inside the package — the
  tooling lives at ``scripts/release_version.py`` (wheel-content fix).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import furl_ctx._version as version_module

_REPO_ROOT = Path(__file__).resolve().parents[1]

_NO_SUBPROCESS_PROBE = """
import subprocess, sys

spawned = []

_real_popen_init = subprocess.Popen.__init__

def _spy(self, *args, **kwargs):
    spawned.append(args[0] if args else kwargs.get("args"))
    return _real_popen_init(self, *args, **kwargs)

subprocess.Popen.__init__ = _spy

import furl_ctx

resolved = furl_ctx.__version__
assert isinstance(resolved, str) and resolved, f"bad __version__: {resolved!r}"
assert not spawned, f"import/__version__ spawned subprocesses: {spawned!r}"
sys.stdout.write(resolved)
"""


class TestNoSubprocessOnImport:
    def test_import_and_version_access_spawn_no_subprocess(self) -> None:
        """Run the probe in a CHILD interpreter from the repo checkout (the
        exact shape that used to trigger the git subprocesses): any
        ``subprocess.Popen`` during import or ``__version__`` access —
        git or otherwise — fails the probe."""
        result = subprocess.run(
            [sys.executable, "-c", _NO_SUBPROCESS_PROBE],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip()


class TestVersionResolution:
    def test_dunder_version_is_a_nonempty_string(self) -> None:
        import furl_ctx

        assert isinstance(furl_ctx.__version__, str)
        assert furl_ctx.__version__

    def test_dunder_version_listed_in_dir(self) -> None:
        import furl_ctx

        assert "__version__" in dir(furl_ctx)
        assert "__version__" in dir(version_module)

    def test_get_version_falls_back_to_unknown_when_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from importlib.metadata import PackageNotFoundError

        def _missing(_name: str) -> str:
            raise PackageNotFoundError(_name)

        monkeypatch.setattr(version_module, "version", _missing)
        assert version_module.get_version() == version_module.UNKNOWN_VERSION

    def test_unknown_attribute_still_raises(self) -> None:
        with pytest.raises(AttributeError):
            _ = version_module.definitely_not_an_attribute


class TestReleaseToolingLeftTheWheel:
    def test_release_version_module_is_gone_from_the_package(self) -> None:
        assert importlib.util.find_spec("furl_ctx.release_version") is None
        assert not (_REPO_ROOT / "furl_ctx" / "release_version.py").exists()

    def test_release_tooling_lives_in_scripts(self) -> None:
        assert (_REPO_ROOT / "scripts" / "release_version.py").exists()

    def test_release_workflow_points_at_scripts_path(self) -> None:
        workflow = (_REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
        assert "python scripts/release_version.py" in workflow
        assert "furl_ctx/release_version.py" not in workflow
