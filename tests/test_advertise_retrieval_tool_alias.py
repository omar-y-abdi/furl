"""NR2-5: `advertise_retrieval_tool` kwarg + one-release `enable_ccr_marker` alias.

The FFI kwarg `enable_ccr_marker` was renamed to `advertise_retrieval_tool`
(the old name invited reading it as a marker/persist gate — it never was; it
gates ONLY the retrieval-tool advertisement, per DOC-20 / Defect 1). The old
kwarg is accepted as a deprecation alias for exactly one release:

* new name works and sets the field;
* old name works, sets the field, and emits ``DeprecationWarning``;
* passing both raises ``ValueError`` naming both.

The alias lives at the pyo3 ``SmartCrusherConfig.__new__`` boundary
(``crates/furl-py/src/lib.rs``) — there is no Python dataclass field for it;
the Python shim derives it from ``CCRConfig`` and forwards it explicitly.
"""

from __future__ import annotations

import pytest

import furl_ctx._core as _core

_DEPRECATION_MSG = "enable_ccr_marker is deprecated, use advertise_retrieval_tool"


def test_new_name_true_sets_field() -> None:
    cfg = _core.SmartCrusherConfig(advertise_retrieval_tool=True)
    assert cfg.advertise_retrieval_tool is True


def test_new_name_false_sets_field() -> None:
    cfg = _core.SmartCrusherConfig(advertise_retrieval_tool=False)
    assert cfg.advertise_retrieval_tool is False


def test_default_is_true_when_neither_passed() -> None:
    cfg = _core.SmartCrusherConfig()
    assert cfg.advertise_retrieval_tool is True


def test_old_name_still_works_and_warns() -> None:
    with pytest.warns(DeprecationWarning, match=_DEPRECATION_MSG) as record:
        cfg = _core.SmartCrusherConfig(enable_ccr_marker=False)
    assert cfg.advertise_retrieval_tool is False
    # The message steers the caller to the replacement + removal timeline.
    assert "advertise_retrieval_tool" in str(record[0].message)
    assert "removed in the next minor release" in str(record[0].message)


def test_old_name_true_maps_through() -> None:
    with pytest.warns(DeprecationWarning, match=_DEPRECATION_MSG):
        cfg = _core.SmartCrusherConfig(enable_ccr_marker=True)
    assert cfg.advertise_retrieval_tool is True


def test_both_names_raises_valueerror_naming_both() -> None:
    with pytest.raises(ValueError) as exc_info:
        _core.SmartCrusherConfig(
            advertise_retrieval_tool=True,
            enable_ccr_marker=True,
        )
    msg = str(exc_info.value)
    assert "advertise_retrieval_tool" in msg
    assert "enable_ccr_marker" in msg


def test_new_name_does_not_warn() -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        cfg = _core.SmartCrusherConfig(advertise_retrieval_tool=True)
    assert cfg.advertise_retrieval_tool is True
