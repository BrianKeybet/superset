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
"""Superset AI Agent - LangChain integration with Superset MCP service.

This module uses Superset's native MCP (Model Context Protocol) service to provide
rich tool capabilities to the AI agent. The MCP service runs on localhost:5008 and
provides tools for dashboard management, chart manipulation, data querying, and more.

Available MCP Tools:
- Dashboard Management: list, create, update, and manage dashboards
- Chart Operations: create, modify, preview, and get chart data
- Dataset Access: list, explore schema, and query datasets
- SQL Lab Integration: execute SQL queries with database context
- System Information: instance metadata, metrics, and health checks

The agent automatically discovers and uses these tools for natural language queries.
"""

import logging
import time
import warnings
from typing import Any

from langchain_core.messages import AIMessageChunk, SystemMessage

from superset.ai_assistant.config import (
    get_llm_cache_key,
    get_llm_instance,
    get_llm_provider,
)
from superset.ai_assistant.mcp_client import get_mcp_tools
from superset.utils import json

# langgraph emits noisy DeprecationWarnings; filter before importing it.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langgraph")

from langgraph.prebuilt import create_react_agent  # noqa: E402

logger = logging.getLogger(__name__)

# Cache compiled agents by resolved LLM config so we don't rebuild the LLM,
# rediscover MCP tools, and recompile the LangGraph graph on every request.
_agent_cache: dict[tuple[str, str, float, int, bool], Any] = {}

# System prompt for the AI assistant using MCP tools.
# Kept intentionally tight: every behavioral rule appears exactly once, and the
# agent is told to work silently (no step-by-step narration). This is the long,
# static prefix served from Anthropic's prompt cache (see _build_system_prompt).
SYSTEM_PROMPT = """You are a precise, tool-first AI assistant embedded in Apache Superset. You help users explore data, build charts, and manage dashboards using only information verified through Superset's MCP tools.

Never guess, infer, or fabricate names or identifiers for tables, schemas, columns, charts, or dashboards. If you lack tool-confirmed data, discover it or say you don't have it.

GREETING
Greet the user by name only in your first reply of a conversation, using the name given in the request context (shown as "[User] <name>"). Never call a tool to obtain the user's identity. Do not repeat the greeting on later turns.

CAPABILITIES
You have MCP tools across five domains: dashboard management (list/create/modify), chart operations (list/create/preview/extract data/configure), dataset & schema discovery (list datasets, inspect schemas, explore columns/metrics), SQL Lab (execute queries, generate pre-filled SQL Lab links), and system info (instance stats, configuration, health).

CURRENT CONTEXT
When the request includes the user's current view (a "[Context]" block with the dashboard/chart/dataset id and a resolved summary), use it: add new charts to the current dashboard, modify the referenced chart without asking which one, and resolve phrases like "this dashboard". If no context is given and the target is unclear, ask instead of guessing.

OPERATING RULES
1. Discover before acting: call the relevant list_* tool (list_datasets / list_charts / list_dashboards) before referencing any resource by name.
2. Validate before SQL: call get_dataset_info to confirm table, schema, and database before running any query — even if you think you know them.
3. Never fabricate identifiers: use only names and ids returned by tools.
4. On tool error, re-discover — never retry with guessed inputs. Return to the list_* tools to find the correct resource, then re-validate before proceeding.
5. When a request is ambiguous and discovery doesn't resolve it, ask a clarifying question or present the available options.
6. Verify mutations: after any create/update/add/delete, check the response for errors, then re-read with a read tool (list_* or get_*_info) to confirm the resource actually persisted. Never trust a write response blindly; if you cannot confirm persistence, flag it.
7. Confirm the dataset for vague data requests: if the request doesn't identify exactly one dataset (e.g. "show me sales data", or a name that matches multiple datasets or the same name across schemas), call list_datasets, present the matches with name + schema + database, and wait for the user to choose one before querying, charting, or inspecting schema.

WORKFLOW
For each data or chart task: discover → disambiguate (Rule 7; wait for confirmation if triggered) → validate with get_*_info → execute → verify writes by re-reading → report. Don't skip or reorder steps. If discovery finds nothing useful, tell the user before proceeding.

OUTPUT
Work silently. Do not narrate tool calls, internal steps, plans, or verification — the user must never see the machinery. Respond only with what the user asked for: the result or data, a brief plain-language summary, and any relevant next step. When presenting datasets for disambiguation, include schema and database so similar names are distinguishable. If a task can't be completed (missing permissions, empty results, unresolved ambiguity) or a write can't be verified, say so plainly and offer a concrete recovery path. Use Markdown (tables, lists, bold) where it aids readability."""


# Maps a context id key to the MCP discovery tool that resolves it, plus a
# human label used in the injected context block.
_CONTEXT_INFO_TOOLS: dict[str, tuple[str, str]] = {
    "dashboard_id": ("get_dashboard_info", "dashboard"),
    "chart_id": ("get_chart_info", "chart"),
    "dataset_id": ("get_dataset_info", "dataset"),
}

# Short-lived process cache for resolved context info, keyed by
# (tool_name, identifier) -> (expires_at_monotonic, resolved_info). The context
# block is now built once per conversation (first turn only), so this mainly
# spares repeat MCP lookups when several conversations start on the same view
# within the TTL window. Only successful lookups are cached, so failures retry.
_CONTEXT_INFO_TTL_SECONDS = 60
_context_info_cache: dict[tuple[str, str], tuple[float, Any]] = {}


def _current_user_display_name() -> str | None:
    """Best-effort human name for the current user, for a free greeting.

    Lets us inject "[User] <name>" instead of forcing the model to spend a
    get_current_user_info tool round-trip on the first turn. Never raises — the
    greeting is cosmetic, so any failure simply means no name is injected.
    """
    try:
        from flask_login import current_user

        if not getattr(current_user, "is_authenticated", False):
            return None
        first = getattr(current_user, "first_name", None) or ""
        last = getattr(current_user, "last_name", None) or ""
        full = f"{first} {last}".strip()
        return full or getattr(current_user, "username", None)
    except Exception:  # noqa: BLE001 - greeting is best-effort
        return None


def _fetch_resource_info(tool: Any, identifier: Any) -> Any:
    """Invoke a wrapped MCP discovery tool for a single identifier.

    Returns the parsed result (dict/list) when the tool returns JSON, the raw
    string otherwise, or None on any failure — enrichment is best-effort and
    must never break the chat request.
    """
    try:
        raw = tool.func({"identifier": identifier})
    except Exception as e:  # noqa: BLE001 - best-effort enrichment
        logger.debug("Context enrichment call failed for %s: %s", identifier, e)
        return None
    if isinstance(raw, str):
        # The tool wrapper returns an error string (prefixed with ❌) instead of
        # raising; treat that as "no info" so we fall back to the bare id rather
        # than injecting an internal error message into the prompt.
        if raw.lstrip().startswith("❌"):
            logger.debug("Context enrichment tool error for %s: %s", identifier, raw)
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    return raw


def _cached_resource_info(tool: Any, identifier: Any) -> Any:
    """Resolve context info via the MCP tool, memoized for a short TTL.

    Caches only successful lookups (see :data:`_context_info_cache`) so a
    transient failure isn't pinned for the whole window.
    """
    key = (tool.name, str(identifier))
    now = time.monotonic()
    cached = _context_info_cache.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]
    info = _fetch_resource_info(tool, identifier)
    if info is not None:
        _context_info_cache[key] = (now + _CONTEXT_INFO_TTL_SECONDS, info)
    return info


def _build_context_block(context: dict[str, Any]) -> str:
    """Build a compact, resolved description of what the user is viewing.

    For each id present in ``context`` (dashboard/chart/dataset), calls the
    matching in-process MCP discovery tool once and inlines a trimmed summary,
    so the agent knows the concrete title/columns up front instead of spending
    extra tool round-trips resolving "this dashboard". Falls back to the bare
    id if the lookup fails or the tool is unavailable.
    """
    present = [
        (key, context.get(key)) for key in _CONTEXT_INFO_TOOLS if context.get(key)
    ]
    if not present:
        return ""

    try:
        tools_by_name = {tool.name: tool for tool in get_mcp_tools()}
    except Exception as e:  # noqa: BLE001 - best-effort enrichment
        logger.debug("Could not load MCP tools for context enrichment: %s", e)
        tools_by_name = {}

    lines = []
    for key, identifier in present:
        tool_name, label = _CONTEXT_INFO_TOOLS[key]
        tool = tools_by_name.get(tool_name)
        info = _cached_resource_info(tool, identifier) if tool else None
        if info is not None:
            summary = json.dumps(info, default=str)
            if len(summary) > 1200:
                summary = summary[:1200] + "…(truncated)"
            lines.append(f"- Current {label} (ID {identifier}): {summary}")
        else:
            lines.append(f"- Current {label}: ID {identifier}")

    return "The user is currently viewing:\n" + "\n".join(lines)


def _content_to_text(content: Any) -> str:
    """Flatten LangChain message content into a plain string.

    Anthropic responses (and some others) return ``content`` as a list of
    content blocks (dicts with a ``text`` field, or plain strings) rather than
    a single string. Join the text parts; fall back to ``str()`` otherwise.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Text blocks carry {"type": "text", "text": "..."}; skip others
                # (e.g. tool_use) which have no user-facing text.
                if block.get("type", "text") == "text" and "text" in block:
                    parts.append(block["text"])
        return "".join(parts)
    return str(content)


def _build_system_prompt() -> Any:
    """Return the system prompt to attach to the agent.

    For Anthropic, wrap it in a cacheable content block so the long, static
    prompt (and the tool definitions rendered before it) are served from
    Anthropic's prompt cache on repeat turns instead of reprocessed every time.
    OpenAI does automatic prefix caching and rejects the ``cache_control`` key,
    so it gets the plain string.
    """
    if get_llm_provider() == "anthropic":
        return SystemMessage(
            content=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        )
    return SYSTEM_PROMPT


def _build_agent(tools: list[Any]) -> Any:
    """Construct a fresh LangGraph ReAct agent for the given tools."""
    llm = get_llm_instance()
    agent = create_react_agent(llm, tools or [], prompt=_build_system_prompt())

    tool_names = [tool.name for tool in (tools or [])]
    if tool_names:
        logger.info(
            "✅ Superset AI Agent initialized with %s MCP tools: %s%s",
            len(tool_names),
            ", ".join(tool_names[:5]),
            "..." if len(tool_names) > 5 else "",
        )
    else:
        logger.error(
            "❌ WARNING: Superset AI Agent created with 0 MCP tools. "
            "The agent will not be able to access Superset data or perform operations."
        )
    return agent


def create_superset_agent(tools: list[Any] | None = None) -> Any:
    """
    Create (or reuse) a LangChain agent using Superset's native MCP tools.

    When ``tools`` is None (the normal path), the compiled agent is cached by
    resolved LLM config and reused across requests — the LLM, MCP tools, and
    LangGraph graph are built once per process. Passing explicit ``tools``
    (e.g. in tests) bypasses the cache and builds a fresh agent.

    Args:
        tools: Optional list of pre-configured tools. If None, tools are
               discovered from the (cached) MCP tool loader.

    Returns:
        Configured LangGraph agent instance

    Raises:
        ValueError: If LLM initialization fails (missing API keys)
    """
    if tools is not None:
        return _build_agent(tools)

    key = get_llm_cache_key()
    if key not in _agent_cache:
        mcp_tools = get_mcp_tools()
        if not mcp_tools:
            logger.error(
                "❌ No MCP tools available. Agent will run without tools, "
                "which severely limits capabilities. Ensure the MCP service is "
                "importable and its tools are registered. Not caching this agent "
                "so a later request can retry once tools are available."
            )
            # Build (uncached) so a subsequent call retries tool discovery.
            return _build_agent([])
        _agent_cache[key] = _build_agent(mcp_tools)

    return _agent_cache[key]


# Write-intent verbs that warrant a post-action verification tip. Deliberately
# excludes bare nouns like "chart"/"dashboard" so pure reads (e.g. "what charts
# are here?") don't get a spurious warning.
_WRITE_INTENT_WORDS = (
    "create",
    "add",
    "update",
    "modify",
    "change",
    "delete",
    "remove",
    "rename",
)


def _verification_note(query: str) -> str:
    """Return a concise post-write verification tip for mutating queries."""
    lowered = query.lower()
    if any(word in lowered for word in _WRITE_INTENT_WORDS):
        return (
            "\n\n---\n⚠️ If the change isn't visible in Superset, refresh the "
            "page and re-check; report it if it's still missing."
        )
    return ""


def _first_turn_preamble(context: dict[str, Any] | None) -> str:
    """Build the once-per-conversation preamble: greeting name + view context.

    Injected only on the first turn (see :func:`_prepare_messages`). Both parts
    are best-effort: the username spares a get_current_user_info round-trip, and
    the resolved context block spares later "what is this dashboard" lookups.
    """
    parts: list[str] = []
    name = _current_user_display_name()
    if name:
        parts.append(f"[User] {name}")
    if context:
        context_block = _build_context_block(context)
        if context_block:
            parts.append(f"[Context]\n{context_block}")
    return "\n\n".join(parts)


def _compact_context_line(context: dict[str, Any]) -> str:
    """One-line current-view reminder (ids only; no MCP lookup).

    Injected on follow-up turns so the agent still knows the current view after
    the first turn's fully-resolved context block scrolls out of the replayed
    history window. Deliberately cheap — a handful of tokens, no tool call.
    """
    parts = [
        f"{label} ID {context[key]}"
        for key, (_tool_name, label) in _CONTEXT_INFO_TOOLS.items()
        if context.get(key)
    ]
    if not parts:
        return ""
    return "The user is currently viewing: " + ", ".join(parts)


def _prepare_messages(
    query: str,
    context: dict[str, Any] | None,
    conversation_history: Any | None,
) -> list[Any]:
    """Build the agent input messages for a turn.

    On the first turn only, enriches the user message with the greeting name and
    the resolved view context; follow-up turns skip that (the info is already in
    the replayed history), avoiding repeated MCP lookups and duplicated tokens.
    Records the user turn in history and prepends the (windowed) prior
    conversation. The system prompt is supplied via the agent's `prompt`, so it
    is not included here. Shared by the blocking and streaming paths.
    """
    # Snapshot prior history *before* recording this turn, so the current
    # message is appended exactly once (get_conversation_context would otherwise
    # already include it — a double-send) and is always present even if
    # persistence fails.
    prior: list[Any] = (
        conversation_history.get_conversation_context() if conversation_history else []
    )
    is_first_turn = not prior

    user_content = query
    if is_first_turn:
        # Full resolved context + greeting name, once per conversation.
        preamble = _first_turn_preamble(context)
        if preamble:
            user_content = f"{query}\n\n{preamble}"
    elif context:
        # Cheap ids-only reminder so view-awareness survives the history window.
        line = _compact_context_line(context)
        if line:
            user_content = f"{query}\n\n[Context]\n{line}"

    if conversation_history:
        conversation_history.add_message("user", user_content)

    return [*prior, {"role": "user", "content": user_content}]


def invoke_agent(
    query: str,
    tools: list[Any] | None = None,
    context: dict[str, Any] | None = None,
    conversation_history: Any | None = None,
) -> dict[str, Any]:
    """
    Invoke the Superset AI agent with a user query.

    The agent will use available MCP tools to answer questions about dashboards,
    charts, datasets, and to perform data operations.

    Args:
        query: User's natural language question or request
        tools: Optional list of tools (if None, MCP tools are discovered automatically)
        context: Optional dictionary with current view context:
            - dashboard_id: Current dashboard ID if user is viewing a dashboard
            - chart_id: Current chart ID if user is viewing a chart
            - dataset_id: Current dataset ID if user is viewing a chart/explore
            - session_id: User's session ID
        conversation_history: Optional ConversationHistory instance for maintaining context

    Returns:
        Dictionary with agent response and metadata:
        {
            "success": bool,
            "response": str (LLM response),
            "error": Optional[str],
            "metadata": {
                "query": original query,
                "tools_used": list of tool names called,
                "conversation_id": conversation ID if history provided
            }
        }

    Raises:
        ValueError: If agent initialization fails
    """
    agent = create_superset_agent(tools)

    try:
        messages = _prepare_messages(query, context, conversation_history)

        logger.info(
            "Invoking agent with %s messages (conversation: %s)",
            len(messages),
            conversation_history.conversation_id if conversation_history else "none",
        )

        # Invoke the agent with the user query
        # LangGraph agents expect messages in a specific format
        response = agent.invoke(
            {
                "messages": messages,
            }
        )

        # Extract the final message from the agent response
        response_messages = response.get("messages", [])
        if not response_messages:
            final_message = "No response from agent"
        else:
            # Get the last message (agent's final response)
            last_msg = response_messages[-1]

            # Handle different message formats (dict vs AIMessage object)
            if isinstance(last_msg, dict):
                content = last_msg.get("content", "No response")
            else:
                # It's an AIMessage or similar object
                content = getattr(last_msg, "content", "No response")

            # Anthropic (and some providers) return content as a list of content
            # blocks rather than a plain string — flatten it to text.
            final_message = _content_to_text(content)

        logger.info("✅ Agent query completed: %s...", query[:60])

        # Record assistant response in conversation history
        if conversation_history:
            conversation_history.add_message("assistant", final_message)

        # Add verification guidance to response
        verification_note = _verification_note(query)

        result = {
            "success": True,
            "response": final_message + verification_note,
            "error": None,
            "metadata": {
                "query": query,
                "message_count": len(messages),
            },
        }

        # Include conversation ID in response for client to use in next request
        if conversation_history:
            result["conversation_id"] = conversation_history.conversation_id

        return result

    except Exception as e:
        error_msg = f"Agent query failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "response": "I encountered an error processing your request. Please try again.",
            "error": str(e),
            "metadata": {"query": query},
        }


def invoke_agent_stream(
    query: str,
    context: dict[str, Any] | None = None,
    conversation_history: Any | None = None,
) -> Any:
    """Stream the agent's response as it is generated.

    Yields ``(event_type, payload)`` tuples so the transport layer can frame
    them (e.g. as SSE):
      - ("token", str)  — an incremental chunk of the assistant's answer
      - ("done", dict)  — final event with `conversation_id` + `verification_note`
      - ("error", str)  — an error occurred mid-stream

    Mirrors `invoke_agent`'s preparation (context enrichment, history recording,
    windowed history) but replaces the blocking `.invoke()` with LangGraph's
    token streaming, and records the full accumulated answer at the end.
    """
    try:
        agent = create_superset_agent()
        messages = _prepare_messages(query, context, conversation_history)

        logger.info(
            "Streaming agent with %s messages (conversation: %s)",
            len(messages),
            conversation_history.conversation_id if conversation_history else "none",
        )

        buffer: list[str] = []
        # stream_mode="messages" yields (message_chunk, metadata) tuples; we keep
        # only the assistant's text chunks (tool messages / tool-call args are
        # not AIMessageChunks or carry no text content).
        for chunk, _metadata in agent.stream(
            {"messages": messages}, stream_mode="messages"
        ):
            if not isinstance(chunk, AIMessageChunk):
                continue
            delta = _content_to_text(chunk.content)
            if delta:
                buffer.append(delta)
                yield ("token", delta)

        final_message = "".join(buffer) or "No response from agent"
        logger.info("✅ Agent stream completed: %s...", query[:60])

        if conversation_history:
            conversation_history.add_message("assistant", final_message)

        done: dict[str, Any] = {"verification_note": _verification_note(query)}
        if conversation_history:
            done["conversation_id"] = conversation_history.conversation_id
        yield ("done", done)

    except Exception as e:
        logger.error("Agent stream failed: %s", str(e), exc_info=True)
        yield ("error", str(e))


# ========================================================================
# NOTE: Custom tool implementations have been removed in favor of using
# Superset's native MCP service tools. The MCP service provides:
#
# - Better integration with Superset's internal APIs
# - Consistent tool behavior across the platform
# - Automatic tool discovery and updates
# - Reduced maintenance burden
# - No database access issues or circular imports
#
# If you need custom tools later, they can be added back as LangChain
# tools and passed to create_superset_agent(tools=[...])
# ========================================================================
