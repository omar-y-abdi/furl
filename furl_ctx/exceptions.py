"""Exception surface for Furl — one reserved base class."""

from __future__ import annotations


# lazy: reserved bare exception
class FurlError(Exception):
    """Base exception for all Furl errors. Reserved."""
