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
"""Tests for the per-model `thinking` setting sent to Anthropic."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("langchain_anthropic")

from superset.ai_assistant.config import _build_llm, thinking_off_config  # noqa: E402


@pytest.mark.parametrize(
    "model, expected",
    [
        ("claude-sonnet-5-5", {"type": "between_tools"}),
        ("claude-opus-5-5", None),
        ("claude-fable-5-1", None),
        ("claude-mythos-5-1", None),
        ("claude-sonnet-5", {"type": "disabled"}),
        ("claude-opus-5", {"type": "disabled"}),
        ("claude-haiku-5-5", {"type": "disabled"}),
        ("Claude-Sonnet-5-5", {"type": "between_tools"}),
    ],
)
def test_thinking_off_config(model: str, expected: dict[str, str] | None) -> None:
    assert thinking_off_config(model) == expected


def _anthropic_kwargs(mocker: Any, model: str) -> dict[str, Any]:
    chat_anthropic = mocker.patch("superset.ai_assistant.config.ChatAnthropic")
    _build_llm("anthropic", model, 0.7, 4096, True)
    return chat_anthropic.call_args.kwargs


@pytest.mark.parametrize(
    "model, expected",
    [
        ("claude-sonnet-5-5", {"type": "between_tools"}),
        ("claude-sonnet-5", {"type": "disabled"}),
    ],
)
def test_build_llm_turns_thinking_off_per_model(
    mocker: Any, monkeypatch: pytest.MonkeyPatch, model: str, expected: dict[str, str]
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("AI_ENABLE_THINKING", raising=False)

    assert _anthropic_kwargs(mocker, model)["thinking"] == expected


def test_build_llm_omits_thinking_when_model_cannot_disable_it(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("AI_ENABLE_THINKING", raising=False)

    assert "thinking" not in _anthropic_kwargs(mocker, "claude-opus-5-5")


def test_build_llm_omits_thinking_when_enabled(
    mocker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AI_ENABLE_THINKING", "true")

    assert "thinking" not in _anthropic_kwargs(mocker, "claude-sonnet-5-5")
