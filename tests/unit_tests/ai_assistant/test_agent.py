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

from superset.utils import json

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
            tool_call_chunks=[{"name": None, "args": "{}", "id": "call_1", "index": 0}],
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

    trace_steps = [
        payload for event_type, payload in results if event_type == "trace_step"
    ]
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


def test_invoke_agent_stream_separates_text_around_tool_calls(
    mocker: Any, app_context: None
) -> None:
    # A note before a tool call, then the answer after it: the two must not
    # run together, in the stream or in the stored answer.
    events = [
        AIMessageChunk(content="Let me check the data."),
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "get_dataset_info", "args": "", "id": "call_1", "index": 0}
            ],
        ),
        ToolMessage(content="{}", name="get_dataset_info", tool_call_id="call_1"),
        AIMessageChunk(content="Here is the "),
        AIMessageChunk(content="answer."),
    ]
    mocker.patch(
        "superset.ai_assistant.agent.create_superset_agent",
        return_value=_fake_agent(events),
    )
    history = MagicMock()
    history.get_conversation_context.return_value = []

    results = list(invoke_agent_stream("question", conversation_history=history))

    tokens = "".join(payload for kind, payload in results if kind == "token")
    assert tokens == "Let me check the data.\n\nHere is the answer."
    history.add_message.assert_any_call(
        "assistant", "Let me check the data.\n\nHere is the answer."
    )


def test_invoke_agent_stream_stores_tool_trail(mocker: Any, app_context: None) -> None:
    events = [
        # Args stream in fragments; continuation chunks carry only the index.
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "execute_sql",
                    "args": '{"sql": "SELECT',
                    "id": "c1",
                    "index": 0,
                }
            ],
        ),
        AIMessageChunk(
            content="",
            tool_call_chunks=[{"name": None, "args": ' 1"}', "id": None, "index": 0}],
        ),
        ToolMessage(
            content="❌ relation does not exist", name="execute_sql", tool_call_id="c1"
        ),
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "get_dataset_info",
                    "args": '{"identifier": 22}',
                    "id": "c2",
                    "index": 0,
                }
            ],
        ),
        ToolMessage(content="{}", name="get_dataset_info", tool_call_id="c2"),
        AIMessageChunk(content="Done."),
    ]
    mocker.patch(
        "superset.ai_assistant.agent.create_superset_agent",
        return_value=_fake_agent(events),
    )
    history = MagicMock()
    history.get_conversation_context.return_value = []

    list(invoke_agent_stream("question", conversation_history=history))

    trail_calls = [
        c.args for c in history.add_message.call_args_list if c.args[0] == "tool_trail"
    ]
    assert trail_calls == [
        (
            "tool_trail",
            '- execute_sql {"sql": "SELECT 1"} -> error: ❌ relation does not exist\n'
            '- get_dataset_info {"identifier": 22} -> ok',
        )
    ]


def test_format_tool_trail_drops_earliest_calls_when_over_budget() -> None:
    from superset.ai_assistant import agent

    calls = [
        {"name": f"tool_{i}", "args": {"x": "y" * 500}, "status": "ok"}
        for i in range(10)
    ]
    trail = agent._format_tool_trail(calls)

    assert len(trail) <= agent._TRAIL_MAX_CHARS + 40
    assert trail.startswith("- (earlier calls omitted)")
    assert "tool_9" in trail
    assert "tool_0 " not in trail


def _fake_tool(name: str, payload: dict[str, Any]) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.func.side_effect = lambda **kwargs: json.dumps(payload)
    return tool


DASHBOARD_DATASETS = {
    "id": 10,
    "dashboard_title": "Kapa Sales Dashboard",
    "datasets": [
        {
            "id": 22,
            "datasource_type": "table",
            "name": "Kapa_Sales_Data",
            "table_name": "Kapa_Sales_Data",
            "schema": "public",
            "database": {"id": 2, "name": "KAPA DW 02", "backend": "postgresql"},
        }
    ],
    "inaccessible_dataset_count": 0,
}

DATASET_INFO = {
    "id": 22,
    "table_name": "Kapa_Sales_Data",
    "schema": "public",
    "database_name": "KAPA DW 02",
    "database_id": 2,
    "is_virtual": True,
    "sql": "SELECT *\n  FROM kapa_sales_summary",
    "main_dttm_col": "INVOICE_DATE",
    "columns": [
        {"column_name": "MO", "type": "STRING", "description": "Invoice month"},
        {"column_name": "NET_AMOUNT", "type": "DECIMAL", "description": None},
    ],
    "metrics": [{"metric_name": "net_sales", "expression": 'SUM("NET_AMOUNT")'}],
}


@pytest.fixture
def context_tools(mocker: Any) -> list[MagicMock]:
    from superset.ai_assistant import agent

    agent._context_info_cache.clear()
    tools = [
        _fake_tool("get_dashboard_datasets", DASHBOARD_DATASETS),
        _fake_tool("get_dataset_info", DATASET_INFO),
    ]
    mocker.patch("superset.ai_assistant.agent.get_mcp_tools", return_value=tools)
    yield tools
    agent._context_info_cache.clear()


def test_context_block_lists_dashboard_datasets_in_detail(
    context_tools: list[MagicMock],
) -> None:
    from superset.ai_assistant.agent import _build_context_block

    block = _build_context_block({"dashboard_id": 10})

    assert '- Current dashboard (ID 10): "Kapa Sales Dashboard".' in block
    assert (
        'Dataset 22 "Kapa_Sales_Data" (schema public, database KAPA DW 02 '
        "(database_id 2)); virtual, not a database table; its SQL: "
        "SELECT * FROM kapa_sales_summary"
    ) in block
    assert 'Saved metrics: net_sales = SUM("NET_AMOUNT")' in block
    assert "Columns: MO (STRING), NET_AMOUNT (DECIMAL)" in block
    assert "Column notes: MO: Invoice month" in block
    assert "Main time column: INVOICE_DATE" in block
    # Tools are called with keyword arguments (the wrapper takes no positionals).
    context_tools[0].func.assert_called_with(request={"identifier": 10})
    # Column descriptions are requested explicitly (not in the tool's default).
    context_tools[1].func.assert_called_with(
        request={
            "identifier": 22,
            "column_fields": ["column_name", "type", "is_dttm", "description"],
        }
    )


def test_compact_context_line_keeps_dataset_identity_only(
    context_tools: list[MagicMock],
) -> None:
    from superset.ai_assistant.agent import _compact_context_line

    line = _compact_context_line({"dashboard_id": 10})

    assert 'Dataset 22 "Kapa_Sales_Data"' in line
    assert "kapa_sales_summary" in line
    assert "Columns:" not in line


def test_context_block_falls_back_to_id_when_lookup_fails(mocker: Any) -> None:
    from superset.ai_assistant import agent

    agent._context_info_cache.clear()
    failing = MagicMock()
    failing.name = "get_dashboard_datasets"
    failing.func.return_value = "❌ Tool get_dashboard_datasets execution failed"
    mocker.patch("superset.ai_assistant.agent.get_mcp_tools", return_value=[failing])

    block = agent._build_context_block({"dashboard_id": 10})

    assert block == "The user is currently viewing:\n- Current dashboard: ID 10"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            "❌ Tool execute_sql execution failed: boom",
            "❌ Tool execute_sql execution failed: boom",
        ),
        (
            '{"success": false, "error": "no such table: t", "error_type": "failed"}',
            "no such table: t",
        ),
        (
            '{"error": "Dataset not found", "error_type": "NotFound"}',
            "Dataset not found",
        ),
        ('{"success": false}', "unsuccessful (no error message)"),
        ('{"success": true, "error": null, "rows": []}', None),
        ('{"data": [], "error": ""}', None),
        ("[1, 2]", None),
        ("plain text result", None),
    ],
)
def test_tool_error_text(content: str, expected: str | None) -> None:
    from superset.ai_assistant.agent import _tool_error_text

    assert _tool_error_text(content) == expected


def test_invoke_agent_stream_treats_json_error_as_failure(
    mocker: Any, app_context: None
) -> None:
    events = [
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {"name": "execute_sql", "args": "{}", "id": "c1", "index": 0}
            ],
        ),
        ToolMessage(
            content='{"success": false, "error": "no such table: kapa_sales_summary"}',
            name="execute_sql",
            tool_call_id="c1",
        ),
    ]
    mocker.patch(
        "superset.ai_assistant.agent.create_superset_agent",
        return_value=_fake_agent(events),
    )
    history = MagicMock()
    history.get_conversation_context.return_value = []

    results = list(invoke_agent_stream("q", conversation_history=history))

    steps = [payload for kind, payload in results if kind == "trace_step"]
    assert steps[-1]["status"] == "error"
    history.add_message.assert_any_call(
        "tool_trail", "- execute_sql {} -> error: no such table: kapa_sales_summary"
    )
