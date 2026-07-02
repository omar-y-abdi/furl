"""Runtime helpers for Claude-facing integrations."""

from __future__ import annotations

DEFAULT_API_URL = "https://api.anthropic.com"


def proxy_base_url(port: int) -> str:
    """Return the local proxy base URL used by Claude integrations."""
    return f"http://127.0.0.1:{port}"
