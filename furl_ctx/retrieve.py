"""Library-side CCR retrieval — turn ``<<ccr:HASH>>`` markers back into content.

The MCP server already exposes retrieve/search; these re-export the same
``CompressionStore`` surface for plain ``from furl_ctx import ...`` users, who
otherwise receive compressed messages carrying markers they cannot resolve.

``retrieve`` mirrors the MCP ``furl_retrieve`` handler's slice filters so a
library caller can drill into a large offloaded original WITHOUT dumping the
whole thing back: a regex/line window over text, a field projection over a JSON
array, or a ROW-SELECT (by value or numeric range) over a JSON array of objects
— including a JSON object with one dominant inner array (the Chrome-trace
shape). With no filter it is byte-identical to a plain full retrieve.
"""

from __future__ import annotations

import re
from typing import Any

from .cache.compression_store import CompressionStore, get_compression_store
from .ccr.marker_grammar import hash_of_match, marker_patterns
from .ccr.retrieve_filters import FilterError, RetrieveFilters, apply_filters

# Distinguishes "select_equals was omitted" from an explicit ``select_equals=None``
# (a real "field is null" match): the MCP dict path keys on presence, and the
# Python keyword path needs the same distinction, which a plain ``None`` default
# cannot express. Never leaks past ``retrieve``.
_UNSET: Any = object()


def retrieve(
    hash: str,
    *,
    query: str | None = None,
    pattern: str | None = None,
    context_lines: int = 0,
    line_range: list[int | None] | None = None,
    fields: list[str] | None = None,
    select_field: str | None = None,
    select_equals: Any = _UNSET,
    select_min: float | None = None,
    select_max: float | None = None,
    limit: int | None = None,
) -> str | None:
    """Return the original content stored under *hash*, or ``None`` on a miss.

    With NO filter argument this is a full retrieve — the byte-exact stored
    original (or ``None`` if the hash is not in the store's window: never stored,
    evicted under capacity, or TTL-expired — a loud, explicit miss, not a silent
    loss). *query* is optional retrieval-event context on that path.

    The filter arguments narrow what comes back, mirroring the MCP
    ``furl_retrieve`` tool and reusing the same validated
    :class:`~furl_ctx.ccr.retrieve_filters.RetrieveFilters` spec:

    * ``pattern`` / ``context_lines`` / ``line_range`` — regex + line window over
      the original as TEXT LINES (matching lines, 1-based numbered).
    * ``fields`` — project named keys out of a JSON ARRAY of objects.
    * ``select_field`` + ``select_equals`` (equality) OR
      ``select_min`` / ``select_max`` (numeric range), with an optional
      ``limit`` — keep the ROWS whose ``select_field`` matches, over a JSON array
      of objects or a JSON object with one dominant inner array. Composes with
      ``fields`` (project columns of the selected rows).

    A filter argument (other than ``query``) makes this a slice: it returns the
    projected text, and ``None`` still means a store miss (the hash resolved to
    nothing). A malformed combination — an invalid regex/range/field list, an
    incompatible filter mix, a ``fields``/select on a non-array original, or
    ``query`` together with a filter — raises :class:`ValueError` (a caller bug,
    surfaced loudly, exactly where the MCP handler returns a structured error).
    """
    filters = RetrieveFilters.parse(
        {
            "pattern": pattern,
            "context_lines": context_lines,
            "line_range": line_range,
            "fields": fields,
            "select_field": select_field,
            # Forward ``select_equals`` only when the caller actually passed one:
            # ``parse`` keys on presence (an equals-null request differs from a
            # range request), and the ``_UNSET`` sentinel preserves that
            # distinction across the keyword boundary.
            **({} if select_equals is _UNSET else {"select_equals": select_equals}),
            "select_min": select_min,
            "select_max": select_max,
            "limit": limit,
        }
    )
    if isinstance(filters, FilterError):
        raise ValueError(filters.reason)
    if query is not None and not filters.is_empty:
        raise ValueError(
            "query cannot be combined with a slice filter (pattern/line_range/"
            "fields/select_*): use query to search within the entry, or a filter "
            "to project the full original"
        )

    entry = get_compression_store().retrieve(hash, query=query)
    if entry is None:
        return None
    if filters.is_empty:
        return entry.original_content

    outcome = apply_filters(entry.original_content, filters)
    if isinstance(outcome, FilterError):
        raise ValueError(outcome.reason)
    return outcome.content


def resolve_markers(
    messages: list[dict[str, Any]], *, store: CompressionStore | None = None
) -> list[dict[str, Any]]:
    """Return a copy of *messages* with every resolvable CCR marker expanded to
    its original content. Unresolvable markers (window miss) are left in place;
    non-string message content is passed through untouched.
    """
    active = store or get_compression_store()

    def _expand(text: str) -> str:
        for pattern in marker_patterns():

            def _sub(match: re.Match[str]) -> str:
                # lazy: bulk expansion does NOT feed the retrieval-feedback loop
                # (record_feedback_signal=False) — it mechanically restores every
                # marker, not the model selectively fetching one.
                entry = active.retrieve(hash_of_match(match), record_feedback_signal=False)
                return entry.original_content if entry is not None else match.group(0)

            text = pattern.sub(_sub, text)
        return text

    resolved: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            resolved.append({**message, "content": _expand(content)})
        else:
            resolved.append(message)
    return resolved
