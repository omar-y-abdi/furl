"""Minimal tests for FurlError."""

from __future__ import annotations
import pytest
from furl_ctx.exceptions import FurlError

def test_is_exception_and_catchable() -> None:
    """A raised FurlError is catchable both as FurlError and Exception."""
    with pytest.raises(FurlError):
        raise FurlError("kaboom")
    assert isinstance(FurlError("x"), Exception)
