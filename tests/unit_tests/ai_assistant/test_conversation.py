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
"""Tests for how stored tool trails are replayed to the agent."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from superset.ai_assistant import conversation
from superset.ai_assistant.conversation import ConversationHistory, TOOL_TRAIL_ROLE


def _history(mocker: Any, rows: list[tuple[str, str]]) -> ConversationHistory:
    """A ConversationHistory over in-memory rows, bypassing the database."""
    conv = MagicMock()
    conv.messages = [
        MagicMock(role=role, content=content, created_on=None) for role, content in rows
    ]
    history = ConversationHistory.__new__(ConversationHistory)
    history.conversation_id = "c"
    mocker.patch.object(history, "_conversation", return_value=conv)
    return history


def test_tool_trail_is_folded_into_its_answer(mocker: Any) -> None:
    history = _history(
        mocker,
        [
            ("user", "q1"),
            ("assistant", "a1"),
            (TOOL_TRAIL_ROLE, "- get_dataset_info {} -> ok"),
            ("user", "q2"),
        ],
    )

    context = history.get_conversation_context()

    assert [m["role"] for m in context] == ["user", "assistant", "user"]
    assert context[1]["content"].startswith("a1\n\n[Tool calls behind this answer")
    assert context[1]["content"].endswith("- get_dataset_info {} -> ok")


def test_tool_trail_is_hidden_from_the_user(mocker: Any) -> None:
    history = _history(
        mocker, [("user", "q1"), ("assistant", "a1"), (TOOL_TRAIL_ROLE, "trail")]
    )

    assert [m["role"] for m in history.get_messages()] == ["user", "assistant"]


def test_only_recent_tool_trails_are_replayed(mocker: Any) -> None:
    rows: list[tuple[str, str]] = []
    for i in range(5):
        rows += [("user", f"q{i}"), ("assistant", f"a{i}"), (TOOL_TRAIL_ROLE, f"t{i}")]
    history = _history(mocker, rows)

    context = history.get_conversation_context()

    with_trail = [m["content"][:2] for m in context if "[Tool calls" in m["content"]]
    assert with_trail == ["a2", "a3", "a4"]
    assert conversation.MAX_REPLAYED_TOOL_TRAILS == 3
