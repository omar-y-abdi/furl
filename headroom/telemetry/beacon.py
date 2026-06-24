"""Telemetry feature-flag helpers for Headroom.

Anonymous usage telemetry is gated behind these environment-variable checks.
The periodic beacon that polled the proxy ``/stats`` route and POSTed aggregate
stats to Supabase was removed alongside the proxy server; only the enable/notice
helpers remain (still consumed by the telemetry collector and CLI output).

On by default. Opt out with:
    HEADROOM_TELEMETRY=off
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


_OFF_VALUES = frozenset(("off", "false", "0", "no", "disable", "disabled"))


def is_telemetry_enabled() -> bool:
    """Check if telemetry is enabled (on by default, opt out with env var)."""
    val = os.environ.get("HEADROOM_TELEMETRY", "on").lower().strip()
    return val not in _OFF_VALUES


def is_telemetry_warn_enabled() -> bool:
    """Check if telemetry warnings are enabled (feature flag, on by default).

    Set HEADROOM_TELEMETRY_WARN=off to suppress startup/wrap notices.
    This is a build/pack-time feature flag intended for operators who want
    to disable the notice without disabling telemetry itself.
    """
    val = os.environ.get("HEADROOM_TELEMETRY_WARN", "on").lower().strip()
    return val not in _OFF_VALUES


def format_telemetry_notice(*, prefix: str = "") -> str:
    """Return a single-line telemetry notice suitable for CLI output.

    Args:
        prefix: Optional leading whitespace / box-drawing prefix.

    Returns an empty string when telemetry or warnings are disabled so callers
    can unconditionally include the result in their output.
    """
    if not is_telemetry_enabled() or not is_telemetry_warn_enabled():
        return ""
    return (
        f"{prefix}Telemetry:    ENABLED (anonymous aggregate stats) | "
        "Disable: HEADROOM_TELEMETRY=off or --no-telemetry"
    )
