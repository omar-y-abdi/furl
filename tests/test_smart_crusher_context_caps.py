"""PERF-12: `_extract_context_from_messages` caps.

The historical sole bound — "stop after 5 user messages" — degenerated to
the FULL history exactly on the common agentic shape (a long single-prompt
session where every other turn is ``role:"tool"``): a 200-turn session
pushed hundreds of KB of query context into Rust BM25 on every crushed
message. The caps pin three properties:

* total collected chars are hard-bounded (``_CONTEXT_MAX_TOTAL_CHARS``);
* assistant tool-call scans are bounded independently of the user-turn
  count (``_CONTEXT_MAX_ASSISTANT_MESSAGES``);
* the walk is newest-first, so capping drops the OLDEST signal first.

NOTE (bench-gate): the caps are a deliberate, slight relevance-signal
change on degenerate long histories — gate on the compression benchmarks,
not byte-equality of context strings.
"""

from __future__ import annotations

from typing import Any

from furl_ctx.transforms.smart_crusher import (
    _CONTEXT_MAX_ASSISTANT_MESSAGES,
    _CONTEXT_MAX_TOTAL_CHARS,
    _CONTEXT_MAX_USER_MESSAGES,
    SmartCrusher,
)


def _extract(messages: list[dict[str, Any]]) -> str:
    return SmartCrusher()._extract_context_from_messages(messages)


def _assistant_turn(i: int) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": f"c{i}",
                "function": {"name": "run_query", "arguments": f'{{"marker": "arg{i}"}}'},
            }
        ],
    }


def _tool_turn(i: int) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": f"c{i}", "content": f"tool output body {i}"}


class TestTotalCharsCap:
    def test_single_prompt_long_agent_session_is_hard_bounded(self) -> None:
        """The degenerate shape: ONE user turn, then 200 assistant/tool
        turns with fat tool-call arguments. Previously the whole history
        was swept into the context; now the total is hard-capped."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "find the failing rows in the audit table please"}
        ]
        for i in range(200):
            turn = _assistant_turn(i)
            turn["tool_calls"][0]["function"]["arguments"] = (
                f"SELECT * FROM somewhere WHERE detail = 'x' AND id = {i} " * 40
            )
            messages.append(turn)
            messages.append(_tool_turn(i))

        context = _extract(messages)

        assert 0 < len(context) <= _CONTEXT_MAX_TOTAL_CHARS + len(context.split()) // 1 + 200
        # Sum of collected parts (join separators aside) never exceeds the cap.
        assert sum(len(p) for p in context.split(" ")) <= _CONTEXT_MAX_TOTAL_CHARS

    def test_oversized_single_user_message_is_truncated_not_dropped(self) -> None:
        huge = "needle-head " + "x" * (3 * _CONTEXT_MAX_TOTAL_CHARS)
        context = _extract([{"role": "user", "content": huge}])

        assert len(context) == _CONTEXT_MAX_TOTAL_CHARS
        assert context.startswith("needle-head ")

    def test_newest_signal_survives_capping(self) -> None:
        """The walk is newest-first: when the cap trims, it is the OLDEST
        content that goes."""
        filler = "y" * _CONTEXT_MAX_TOTAL_CHARS  # alone exhausts the cap
        messages = [
            {"role": "user", "content": "ancient-marker question from long ago"},
            {"role": "user", "content": filler},
            {"role": "user", "content": "fresh-marker most recent question"},
        ]

        context = _extract(messages)

        assert "fresh-marker" in context
        assert "ancient-marker" not in context


class TestAssistantScanCap:
    def test_assistant_tool_call_scan_bounded_without_user_turns(self) -> None:
        """30 assistant turns, one user turn: only the newest
        ``_CONTEXT_MAX_ASSISTANT_MESSAGES`` assistant messages contribute
        their tool-call arguments."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": "single prompt"}]
        for i in range(30):
            messages.append(_assistant_turn(i))
            messages.append(_tool_turn(i))

        context = _extract(messages)

        # Newest assistant turn contributes; the ones older than the cap do not.
        assert "arg29" in context
        assert f"arg{29 - (_CONTEXT_MAX_ASSISTANT_MESSAGES - 1)}" in context
        assert f"arg{29 - _CONTEXT_MAX_ASSISTANT_MESSAGES}" not in context
        assert "single prompt" in context

    def test_assistant_messages_without_tool_calls_do_not_consume_the_cap(self) -> None:
        messages: list[dict[str, Any]] = [{"role": "user", "content": "prompt"}]
        for i in range(40):
            messages.append({"role": "assistant", "content": f"plain reply {i}"})
        messages.append(_assistant_turn(99))

        context = _extract(messages)

        assert "arg99" in context


class TestHistoricalBehaviorPreserved:
    def test_short_conversation_output_is_unchanged(self) -> None:
        """Under every cap, the collected context matches the historical
        shape: newest-first user texts + tool-call args, space-joined."""
        messages = [
            {"role": "user", "content": "first question"},
            _assistant_turn(1),
            _tool_turn(1),
            {"role": "user", "content": "second question"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "block text part"},
                    {"type": "image", "source": "ignored"},
                ],
            },
        ]

        context = _extract(messages)

        assert context == 'block text part second question {"marker": "arg1"} first question'

    def test_user_turn_cap_unchanged(self) -> None:
        messages = [{"role": "user", "content": f"user turn {i}"} for i in range(12)]

        context = _extract(messages)

        assert f"user turn {11}" in context
        assert f"user turn {12 - _CONTEXT_MAX_USER_MESSAGES}" in context
        assert f"user turn {11 - _CONTEXT_MAX_USER_MESSAGES}" not in context
