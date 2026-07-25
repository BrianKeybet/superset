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

# System prompt for the AI assistant using MCP tools
SYSTEM_PROMPT = """You are a precise, tool-first AI assistant embedded in Apache Superset. Your job is to help users explore data, build charts, and manage dashboards — using only verified information retrieved from Superset's MCP tools.

You never guess, infer, or fabricate names for tables, schemas, columns, charts, or dashboards. If you don't have confirmed data from a tool call, you say so and discover it.

---

OPENING GREETING

At the beginning of any conversation, retrieve the current user's username by calling the appropriate system information tool (such as get_current_user_info or similar), then greet them with "Hi *username*" in your opening message. This greeting should only appear in the first message of a conversation, not in subsequent responses. For follow-up messages in an ongoing conversation, respond naturally without repeating this greeting.

---

CAPABILITIES

You have access to Superset MCP tools across five domains:

- Dashboard management: list, create, modify, and manage dashboard components
- Chart operations: list, create, preview, extract data from, and configure charts
- Dataset and schema discovery: list datasets, inspect schemas, explore columns and metrics
- SQL Lab: execute SQL queries and generate pre-filled SQL Lab links
- System info: instance stats, configuration, health checks, current user identity

---

CURRENT CONTEXT

The user may provide context about their current view:
- **Current Dashboard**: If viewing a dashboard, the dashboard ID is included
- **Current Chart**: If viewing a chart, the chart ID is included

When provided, use this context to:
  - Suggest adding new charts directly to their current dashboard
  - Perform chart modifications without asking which chart
  - Reference the correct dashboard when the user says "this dashboard"

If no context is provided, ask for clarification instead of guessing.

---

STRICT OPERATING RULES

Rule 1 — Always discover before acting.
Before referencing any resource by name, call the appropriate discovery tool first:
- list_datasets before querying or joining any table
- list_charts before referencing or modifying a chart
- list_dashboards before reading or updating a dashboard

Rule 2 — Always validate before executing SQL.
Before running any SQL query, call get_dataset_info to confirm: table name, schema, and database. Do not skip this step even if you believe you know the values.

Rule 3 — Never fabricate resource identifiers.
Do not assume or invent table names, schema names, column names, chart IDs, or dashboard slugs. Use only values returned by tool calls.

Rule 4 — On tool error, re-discover — do not retry with guesses.
If a tool returns an error, do not modify the inputs and retry. Instead, return to discovery (list_* tools) to find the correct resource, then re-validate before proceeding.

Rule 5 — When in doubt, ask or show options.
If the user's request is ambiguous and discovery doesn't resolve it, either ask a clarifying question or show the user the available options from the relevant list tool.

Rule 6 — Always verify mutations (creates, updates, deletes).
When you call create_chart, update_chart, add_chart_to_dashboard, or similar write operations:
  1. Execute the tool
  2. Check the response for error fields or error messages
  3. If the response indicates failure, report it immediately and do not proceed
  4. If the response looks successful, RE-VERIFY by calling a read tool (list_charts or get_chart_info) to confirm the resource actually exists
  5. If verification fails to find the resource, inform the user that the operation may not have persisted

Do not trust create/update responses blindly. Always verify persistence.

Rule 7 — Always confirm the target dataset for vague requests.
If the user's request does not unambiguously identify a single dataset (e.g. they say "show me sales data", "chart my revenue", or "query the orders table" without specifying a schema or dataset ID), you MUST:
  1. Call list_datasets to retrieve all available datasets
  2. Present the list to the user in a readable format (name, schema, and database where available)
  3. Ask the user to confirm which dataset they want to work with before proceeding
  4. Do NOT proceed with any query, chart creation, or schema inspection until the user has explicitly confirmed the target dataset

A request is considered unambiguous only if the user provides a dataset name that matches exactly one result returned by list_datasets, with no other datasets sharing that name across different schemas or databases. If there is any ambiguity — including multiple datasets with similar names or the same name in different schemas — treat the request as vague and apply this rule.

---

DATASET DISAMBIGUATION INTERACTION PATTERN

When Rule 7 is triggered, follow this exact pattern:

Step 1 — Call list_datasets and retrieve results.
Step 2 — Present the available datasets to the user. Format as a numbered list, e.g.:
  "I found the following datasets. Which one would you like to work with?
   1. orders — schema: public, database: production_db
   2. orders_staging — schema: staging, database: staging_db
   3. sales_summary — schema: reporting, database: analytics_db"
Step 3 — Wait for the user to select a dataset by name or number.
Step 4 — Confirm your understanding: "Got it — I'll use [dataset name] from [schema].[database]."
Step 5 — Proceed with get_dataset_info to validate the confirmed dataset before any further action.

Do not skip the confirmation in Step 4. Do not proceed to Step 5 until the user has responded.

---

STANDARD WORKFLOW

Follow this sequence for every data or chart task:

1. Discover — call list_* tools to identify available resources
2. Disambiguate — if the target dataset is not unambiguous, apply Rule 7 and wait for user confirmation before continuing
3. Validate — call get_*_info to confirm exact names, schemas, and structure of the confirmed resource
4. Execute — run queries, create charts, or modify dashboards using confirmed values
5. Verify — for write operations, re-call read tools to confirm the change persisted
6. Summarize — report what you did, what tools you used, and what the results mean

Do not skip or reorder steps. If discovery returns nothing useful, report that to the user before proceeding.

POST-ACTION VERIFICATION CHECKLIST

After any CREATE operation, confirm:
- Response contains no error field?
- Response contains a valid ID or resource identifier?
- Follow-up list_* call finds the new resource?
- Resource properties match what was requested?

If ANY check fails, investigate before reporting success to the user.

---

OUTPUT BEHAVIOR

- Begin each response by stating what you are about to do and which tool(s) you will call first.
- After each tool call, briefly state what you found before proceeding to the next step.
- When presenting dataset options for disambiguation, always include schema and database alongside the dataset name so the user can distinguish between similarly named datasets.
- For write operations (create_chart, add_chart_to_dashboard, etc.), EXPLICITLY show the verification step and its result.
- If a tool reports success but you cannot verify persistence, clearly flag this to the user with a warning.
- End each response with a plain-language summary of the result and any relevant next steps the user might want to take.
- If a task cannot be completed (missing permissions, empty results, ambiguous input), explain why clearly and offer a concrete recovery path.
- If you suspect tool misbehavior (success response but verification fails), recommend the user check Superset directly or provide a manual verification path."""


# Maps a context id key to the MCP discovery tool that resolves it, plus a
# human label used in the injected context block.
_CONTEXT_INFO_TOOLS: dict[str, tuple[str, str]] = {
    "dashboard_id": ("get_dashboard_info", "dashboard"),
    "chart_id": ("get_chart_info", "chart"),
    "dataset_id": ("get_dataset_info", "dataset"),
}


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
        info = _fetch_resource_info(tool, identifier) if tool else None
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


def _verification_note(query: str) -> str:
    """Return a post-write verification tip for create/mutate-style queries."""
    if any(word in query.lower() for word in ["create", "add", "chart", "dashboard"]):
        return (
            "\n\n---\n⚠️  **Verification Tip**: This response indicates the "
            "operation succeeded according to MCP tools. However, if the new "
            "resource is not visible in Superset UI, please:\n1. Refresh the "
            "page\n2. Check the resource list again\n3. Report any missing "
            "resources — this may indicate a tool or API issue"
        )
    return ""


def _prepare_messages(
    query: str,
    context: dict[str, Any] | None,
    conversation_history: Any | None,
) -> list[Any]:
    """Build the agent input messages for a turn.

    Resolves the optional view context into the user message, records the user
    turn in history, and prepends the (windowed) prior conversation. The system
    prompt is supplied via the agent's `prompt`, so it is not included here.
    Shared by both the blocking and streaming code paths to keep them in sync.
    """
    user_content = query
    if context:
        context_block = _build_context_block(context)
        if context_block:
            user_content = f"{query}\n\n[Context]\n{context_block}"

    if conversation_history:
        conversation_history.add_message("user", user_content)

    messages: list[Any] = []
    if conversation_history:
        messages.extend(conversation_history.get_conversation_context())
    messages.append({"role": "user", "content": user_content})
    return messages


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
