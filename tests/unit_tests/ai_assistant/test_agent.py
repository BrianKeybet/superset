#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Tests for the streaming trace_step events emitted by invoke_agent_stream.

The AI Assistant's LangChain/LangGraph dependencies are optional (installed
via requirements/ai-assistant.txt); skip this module entirely when they
aren't available rather than failing collection.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessageChunk, ToolMessage  # noqa: E402

from superset.ai_assistant.agent import (  # noqa: E402
    _tool_label,
    invoke_agent_stream,
)


def _fake_agent(events: list[Any]) -> MagicMock:
    """A stand-in for the compiled LangGraph agent: `.stream()` replays events."""
    agent = MagicMock()
    agent.stream.return_value = iter([(event, {}) for event in events])
    return agent


def test_tool_label_known_tool_uses_friendly_text() -> None:
    assert _tool_label("list_charts") == "Looking through your charts"


def test_tool_label_unknown_tool_falls_back_to_humanized_name() -> None:
    assert _tool_label("some_new_tool") == "Some new tool"


def test_invoke_agent_stream_emits_running_then_done_trace_steps(
    mocker: Any, app_context: None
) -> None:
    events = [
        # First chunk of a tool call: name arrives whole, args stream after.
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "list_charts", "args": "", "id": "call_1", "index": 0}
            ],
        ),
        # A later chunk continuing the same call's args — must not re-announce.
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": None, "args": "{}", "id": "call_1", "index": 0}
            ],
        ),
        ToolMessage(content="[]", name="list_charts", tool_call_id="call_1"),
        AIMessageChunk(content="Here are your charts."),
    ]
    mocker.patch(
        "superset.ai_assistant.agent.create_superset_agent",
        return_value=_fake_agent(events),
    )

    results = list(invoke_agent_stream("what charts do we have?"))

    assert results == [
        (
            "trace_step",
            {
                "id": "call_1",
                "tool": "list_charts",
                "label": "Looking through your charts",
                "status": "running",
            },
        ),
        (
            "trace_step",
            {
                "id": "call_1",
                "tool": "list_charts",
                "label": "Looking through your charts",
                "status": "done",
            },
        ),
        ("token", "Here are your charts."),
        ("done", {"verification_note": ""}),
    ]


def test_invoke_agent_stream_marks_failed_tool_call_as_error(
    mocker: Any, app_context: None
) -> None:
    events = [
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "execute_sql", "args": "", "id": "call_2", "index": 0}
            ],
        ),
        ToolMessage(
            content="❌ Tool execution failed: table not found",
            name="execute_sql",
            tool_call_id="call_2",
        ),
    ]
    mocker.patch(
        "superset.ai_assistant.agent.create_superset_agent",
        return_value=_fake_agent(events),
    )

    results = list(invoke_agent_stream("run this query"))

    trace_steps = [payload for event_type, payload in results if event_type == "trace_step"]
    assert trace_steps[-1]["status"] == "error"
    assert trace_steps[-1]["id"] == "call_2"
    # The trace only ever carries the friendly label, never the raw tool output.
    assert "table not found" not in trace_steps[-1]["label"]


def test_invoke_agent_stream_logs_token_usage_per_turn(
    mocker: Any, app_context: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Two LLM calls in one turn; LangChain's input_tokens includes cache tokens.
    events = [
        AIMessageChunk(
            content="",
            usage_metadata={
                "input_tokens": 1200,
                "output_tokens": 0,
                "total_tokens": 1200,
                "input_token_details": {"cache_read": 1000, "cache_creation": 0},
            },
        ),
        AIMessageChunk(
            content="Done.",
            usage_metadata={
                "input_tokens": 300,
                "output_tokens": 40,
                "total_tokens": 340,
                "input_token_details": {"cache_read": 0, "cache_creation": 100},
            },
        ),
    ]
    mocker.patch(
        "superset.ai_assistant.agent.create_superset_agent",
        return_value=_fake_agent(events),
    )
    mocker.patch(
        "superset.ai_assistant.agent.get_llm_cache_key",
        return_value=("anthropic", "claude-sonnet-5-5", 0.7, 4096, True),
    )

    with caplog.at_level("INFO", logger="superset.ai_assistant.agent"):
        list(invoke_agent_stream("hello"))

    usage_lines = [r.getMessage() for r in caplog.records if "AI usage:" in r.message]
    assert usage_lines == [
        "AI usage: model=claude-sonnet-5-5 input_tokens=400 output_tokens=40 "
        "cache_read_tokens=1000 cache_creation_tokens=100"
    ]


def test_invoke_agent_stream_logs_usage_even_when_stream_fails(
    mocker: Any, app_context: None, caplog: pytest.LogCaptureFixture
) -> None:
    def failing_stream() -> Any:
        yield (
            AIMessageChunk(
                content="",
                usage_metadata={
                    "input_tokens": 500,
                    "output_tokens": 0,
                    "total_tokens": 500,
                },
            ),
            {},
        )
        raise RuntimeError("boom")

    agent = MagicMock()
    agent.stream.return_value = failing_stream()
    mocker.patch(
        "superset.ai_assistant.agent.create_superset_agent", return_value=agent
    )

    with caplog.at_level("INFO", logger="superset.ai_assistant.agent"):
        results = list(invoke_agent_stream("hello"))

    assert results[-1] == ("error", "boom")
    assert any("input_tokens=500" in r.getMessage() for r in caplog.records)
