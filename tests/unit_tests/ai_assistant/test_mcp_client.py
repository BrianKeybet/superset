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
"""Tests for the in-process FastMCP → LangChain tool bridge."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("fastmcp")

from fastmcp import Context, FastMCP  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from superset.ai_assistant import mcp_client  # noqa: E402
from superset.utils import json  # noqa: E402


class LookupRequest(BaseModel):
    identifier: int
    note: str | None = None


class LookupResponse(BaseModel):
    identifier: int
    request_type: str
    note: str | None = None


def _bridged_tools(mocker: Any, app: Any) -> dict[str, Any]:
    """Build LangChain tools from a real FastMCP instance with one tool."""
    server = FastMCP("test")

    @server.tool
    async def lookup(request: LookupRequest, ctx: Context) -> LookupResponse:
        """Look something up."""
        await ctx.info("lookup %s" % (request.identifier,))
        # A plain dict here would raise AttributeError, like the original bug.
        return LookupResponse(
            identifier=request.identifier,
            request_type=type(request).__name__,
            note=request.note,
        )

    mocker.patch("superset.mcp_service.app.mcp", server)
    mocker.patch("superset.mcp_service.app.register_all_tools")
    mocker.patch(
        "superset.mcp_service.app.get_registered_mcp_tools",
        return_value=mcp_client.asyncio.run(server.list_tools()),
    )
    mocker.patch.dict(
        sys.modules,
        {"superset.mcp_service.flask_singleton": types.SimpleNamespace(app=app)},
    )
    return {tool.name: tool for tool in mcp_client._build_mcp_tools()}


def test_bridge_exposes_the_tool_json_schema(mocker: Any, app: Any) -> None:
    tool = _bridged_tools(mocker, app)["lookup"]

    assert set(tool.args) == {"request"}
    assert "identifier" in json.dumps(tool.args["request"])


@pytest.mark.parametrize(
    "tool_input",
    [
        {"request": {"identifier": 10}},
        {"request": {"identifier": "10"}},  # coerced by Pydantic validation
        {"identifier": 10},  # flattened by the model
        {"request": '{"identifier": 10}'},  # request sent as a JSON string
    ],
)
def test_bridge_validates_arguments_into_request_model(
    mocker: Any, app: Any, tool_input: dict[str, Any]
) -> None:
    tool = _bridged_tools(mocker, app)["lookup"]

    with app.test_request_context():
        result = json.loads(tool.invoke(tool_input))

    assert result == {"identifier": 10, "request_type": "LookupRequest", "note": None}


def test_bridge_handles_repeated_calls_in_one_request(mocker: Any, app: Any) -> None:
    tool = _bridged_tools(mocker, app)["lookup"]

    with app.test_request_context():
        results = [
            json.loads(tool.invoke({"request": {"identifier": i}})) for i in range(3)
        ]

    assert [r["identifier"] for r in results] == [0, 1, 2]


def test_bridge_reports_invalid_arguments_as_tool_error(mocker: Any, app: Any) -> None:
    tool = _bridged_tools(mocker, app)["lookup"]

    with app.test_request_context():
        result = tool.invoke({"request": {"identifier": "not-a-number"}})

    assert result.startswith("❌ Tool lookup execution failed:")


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"request": {"a": 1}}, {"request": {"a": 1}}),
        ({"a": 1, "b": 2}, {"request": {"a": 1, "b": 2}}),
        ({"request": '{"a": 1}'}, {"request": {"a": 1}}),
        ({"request": "not json"}, {"request": "not json"}),
        ({}, {"request": {}}),
    ],
)
def test_normalize_tool_arguments_for_request_tools(
    kwargs: dict[str, Any], expected: dict[str, Any]
) -> None:
    tool_obj = types.SimpleNamespace(parameters={"properties": {"request": {}}})

    assert mcp_client._normalize_tool_arguments(tool_obj, kwargs) == expected


def test_normalize_tool_arguments_passes_other_tools_through() -> None:
    tool_obj = types.SimpleNamespace(parameters={"properties": {"sql": {}, "db": {}}})

    assert mcp_client._normalize_tool_arguments(tool_obj, {"sql": "x"}) == {"sql": "x"}


def test_tool_result_to_text() -> None:
    text_block = types.SimpleNamespace(text='{"ok": true}')
    image_block = types.SimpleNamespace(data="...")

    assert (
        mcp_client._tool_result_to_text(
            types.SimpleNamespace(content=[image_block, text_block])
        )
        == '{"ok": true}'
    )
    assert (
        mcp_client._tool_result_to_text(
            types.SimpleNamespace(content=[], structured_content={"ok": True})
        )
        == '{"ok": true}'
    )
    assert mcp_client._tool_result_to_text("plain") == "plain"
    assert mcp_client._tool_result_to_text({"a": 1}) == '{"a": 1}'


def test_bridge_gives_parallel_calls_their_own_g(mocker: Any, app: Any) -> None:
    """Parallel tool calls must not share ``g`` with each other or the request.

    The agent runs parallel tool calls in threads that inherit the request's
    contexts; a shared ``g.user`` was detached by whichever call finished first.
    """
    import contextvars
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from flask import g

    seen: list[tuple[int, Any]] = []
    both_running = threading.Barrier(2, timeout=5)
    server = FastMCP("test")

    @server.tool
    def probe(request: LookupRequest) -> LookupResponse:
        """Record this call's ``g`` while the other call is also running."""
        both_running.wait()
        seen.append((id(g._get_current_object()), g.user))
        g.user = f"changed by {request.identifier}"
        return LookupResponse(identifier=request.identifier, request_type="probe")

    mocker.patch("superset.mcp_service.app.mcp", server)
    mocker.patch("superset.mcp_service.app.register_all_tools")
    mocker.patch(
        "superset.mcp_service.app.get_registered_mcp_tools",
        return_value=mcp_client.asyncio.run(server.list_tools()),
    )
    mocker.patch.dict(
        sys.modules,
        {"superset.mcp_service.flask_singleton": types.SimpleNamespace(app=app)},
    )
    tool = {t.name: t for t in mcp_client._build_mcp_tools()}["probe"]

    with app.test_request_context():
        g.user = "request user"
        request_g = id(g._get_current_object())
        with ThreadPoolExecutor(2) as pool:
            futures = [
                pool.submit(
                    contextvars.copy_context().run,
                    tool.invoke,
                    {"request": {"identifier": i}},
                )
                for i in range(2)
            ]
            results = [json.loads(f.result()) for f in futures]

        assert g.user == "request user"

    assert [r["identifier"] for r in results] == [0, 1]
    assert [user for _, user in seen] == ["request user", "request user"]
    assert len({g_id for g_id, _ in seen} | {request_g}) == 3
