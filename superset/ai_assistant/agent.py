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
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import AIMessageChunk, SystemMessage, ToolMessage

from superset.ai_assistant.config import (
    get_llm_cache_key,
    get_llm_instance,
    get_llm_provider,
)
from superset.ai_assistant.conversation import TOOL_TRAIL_ROLE
from superset.ai_assistant.mcp_client import get_mcp_tools
from superset.utils import json

# langgraph emits noisy DeprecationWarnings; filter before importing it.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langgraph")

from langgraph.prebuilt import create_react_agent  # noqa: E402

logger = logging.getLogger(__name__)


def _add_usage(totals: dict[str, int], usage: Any) -> None:
    """Accumulate a LangChain ``usage_metadata`` dict into ``totals``.

    LangChain reports ``input_tokens`` including cache reads and cache writes;
    they are split out so each token class can be priced separately.
    """
    if not usage:
        return
    details = usage.get("input_token_details") or {}
    cache_read = int(details.get("cache_read") or 0)
    cache_creation = int(details.get("cache_creation") or 0)
    totals["input_tokens"] += max(
        int(usage.get("input_tokens") or 0) - cache_read - cache_creation, 0
    )
    totals["output_tokens"] += int(usage.get("output_tokens") or 0)
    totals["cache_read_tokens"] += cache_read
    totals["cache_creation_tokens"] += cache_creation


def _new_usage_totals() -> dict[str, int]:
    return dict.fromkeys(
        ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"),
        0,
    )


def _log_usage(totals: dict[str, int]) -> None:
    """Log the token usage of one chat turn (all LLM calls of the agent loop).

    The line format is parsed by the deployment's metrics collector; keep it
    stable: ``AI usage: model=<m> input_tokens=<n> output_tokens=<n>
    cache_read_tokens=<n> cache_creation_tokens=<n>``.
    """
    if not any(totals.values()):
        return
    logger.info(
        "AI usage: model=%s input_tokens=%d output_tokens=%d "
        "cache_read_tokens=%d cache_creation_tokens=%d",
        get_llm_cache_key()[1],
        totals["input_tokens"],
        totals["output_tokens"],
        totals["cache_read_tokens"],
        totals["cache_creation_tokens"],
    )


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
1. Discover before acting: call the relevant list_* tool (list_datasets / list_charts / list_dashboards) before referencing any resource by name. Resources described in [Context] or in an earlier turn's tool calls are already discovered.
2. Validate before querying: confirm the dataset's table, schema and database from [Context], an earlier turn's tool calls, or get_dataset_info before any query. Prefer query_dataset (saved metrics, grouping columns, filters) for aggregates. Use execute_sql only for what query_dataset cannot express; then query the dataset's underlying table or SQL (a virtual dataset's name is not a database table) and double-quote identifiers exactly as listed.
3. Never fabricate identifiers: use only names and ids returned by tools.
4. On tool error, re-discover — never retry with guessed inputs. Return to the list_* tools to find the correct resource, then re-validate before proceeding.
5. When a request is ambiguous and discovery doesn't resolve it, ask a clarifying question or present the available options.
6. Verify mutations: after any create/update/add/delete, check the response for errors, then re-read with a read tool (list_* or get_*_info) to confirm the resource actually persisted. Never trust a write response blindly; if you cannot confirm persistence, flag it.
7. Choose the dataset for data requests:
   - If [Context] lists the current dashboard's datasets, use only those. If exactly one fits the request, use it without asking. If several fit, ask which one, listing just those. If none fit, say so and ask which dataset to use.
   - If [Context] gives a chart or a dataset, use that chart's or that dataset's data.
   - If there is no view context and the request doesn't name exactly one dataset, ask the user to specify it before querying, charting, or inspecting schema: call list_datasets and list the likely matches with name, schema and database.

WORKFLOW
For each data or chart task: discover → disambiguate (Rule 7; wait for confirmation if triggered) → validate with get_*_info → execute → verify writes by re-reading → report. Don't skip or reorder steps. If discovery finds nothing useful, tell the user before proceeding.

OUTPUT
Work silently. Do not narrate tool calls, internal steps, plans, or verification — the user must never see the machinery. Respond only with what the user asked for: the result or data, a brief plain-language summary, and any relevant next step. When presenting datasets for disambiguation, include schema and database so similar names are distinguishable. If a task can't be completed (missing permissions, empty results, unresolved ambiguity) or a write can't be verified, say so plainly and offer a concrete recovery path. Use Markdown (tables, lists, bold) where it aids readability."""


# Maps a context id key to the MCP discovery tool that resolves it, plus a
# human label used in the injected context block. A dashboard resolves to the
# datasets behind its charts, which is what data questions on it need.
_CONTEXT_INFO_TOOLS: dict[str, tuple[str, str]] = {
    "dashboard_id": ("get_dashboard_datasets", "dashboard"),
    "chart_id": ("get_chart_info", "chart"),
    "dataset_id": ("get_dataset_info", "dataset"),
}

# Extra request fields per context lookup tool. get_dataset_info returns only
# name/type/is_dttm per column by default; the descriptions say how to use them.
_CONTEXT_EXTRA_ARGS: dict[str, dict[str, Any]] = {
    "get_dataset_info": {
        "column_fields": ["column_name", "type", "is_dttm", "description"],
    },
}

# Datasets of the current dashboard described in full (columns, metrics, SQL);
# any beyond this are listed by name only.
_MAX_DETAILED_DATASETS = 3
# Caps that keep the injected context block small.
_MAX_CONTEXT_SQL_CHARS = 400
_MAX_CONTEXT_EXPRESSION_CHARS = 80
_MAX_CONTEXT_DESCRIPTION_CHARS = 200
_MAX_GENERIC_INFO_CHARS = 1200

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
        # The wrapped tools take keyword arguments only; their single
        # parameter is the request model.
        request = {"identifier": identifier, **_CONTEXT_EXTRA_ARGS.get(tool.name, {})}
        raw = tool.func(request=request)
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


def _clip(text: Any, limit: int) -> str:
    """Collapse whitespace and cap ``text`` at ``limit`` characters."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _dataset_location(info: dict[str, Any]) -> str:
    """'schema public, database X' from a dataset or dashboard-dataset dict."""
    schema = info.get("schema") or info.get("schema_name")
    database = info.get("database_name")
    if database is None and isinstance(info.get("database"), dict):
        database = info["database"].get("name")
    parts = []
    if schema:
        parts.append(f"schema {schema}")
    if database:
        parts.append(f"database {database}")
    return ", ".join(parts)


def _dataset_heading(info: dict[str, Any]) -> str:
    """One-line identity of a dataset, including what a virtual one reads."""
    name = info.get("table_name") or info.get("name")
    heading = f'Dataset {info.get("id")} "{name}"'
    if location := _dataset_location(info):
        heading += f" ({location})"
    if info.get("is_virtual") and info.get("sql"):
        heading += (
            "; virtual, not a database table; its SQL: "
            f"{_clip(info['sql'], _MAX_CONTEXT_SQL_CHARS)}"
        )
    return heading


def _format_dataset_detail(info: dict[str, Any]) -> str:
    """Describe a dataset from get_dataset_info output for the context block.

    Gives the agent what it needs to query without another lookup: the exact
    column names and types, saved metrics, the main time column, the SQL of a
    virtual dataset, and any descriptions.
    """
    lines = [f"  - {_dataset_heading(info)}"]
    if info.get("description"):
        lines.append(
            "    Description: "
            f"{_clip(info['description'], _MAX_CONTEXT_DESCRIPTION_CHARS)}"
        )
    if info.get("main_dttm_col"):
        lines.append(f"    Main time column: {info['main_dttm_col']}")
    metrics = [
        f"{m.get('metric_name')} = "
        f"{_clip(m.get('expression') or '', _MAX_CONTEXT_EXPRESSION_CHARS)}"
        for m in info.get("metrics") or []
        if m.get("metric_name")
    ]
    if metrics:
        lines.append("    Saved metrics: " + "; ".join(metrics))
    columns = info.get("columns") or []
    if columns:
        lines.append(
            "    Columns: "
            + ", ".join(
                f"{c.get('column_name')} ({c.get('type') or '?'})"
                for c in columns
                if c.get("column_name")
            )
        )
    notes = [
        f"{c.get('column_name')}: "
        f"{_clip(c['description'], _MAX_CONTEXT_DESCRIPTION_CHARS)}"
        for c in columns
        if c.get("description")
    ]
    if notes:
        lines.append("    Column notes: " + " | ".join(notes))
    return "\n".join(lines)


def _describe_dashboard(
    identifier: Any,
    info: dict[str, Any],
    dataset_tool: Any | None,
    detailed: bool,
) -> str:
    """Describe the current dashboard by the datasets behind its charts.

    Each dataset is resolved with get_dataset_info so a virtual one shows the
    SQL it reads; the first few get full detail when ``detailed``.
    """
    title = info.get("dashboard_title") or ""
    lines = [
        f'- Current dashboard (ID {identifier}): "{title}". '
        "Datasets used by its charts:"
    ]
    datasets = [
        d for d in info.get("datasets") or [] if d.get("datasource_type") == "table"
    ]
    for position, summary in enumerate(datasets):
        full = (
            _cached_resource_info(dataset_tool, summary.get("id"))
            if dataset_tool
            else None
        )
        if not isinstance(full, dict):
            lines.append(f"  - {_dataset_heading(summary)}")
        elif detailed and position < _MAX_DETAILED_DATASETS:
            lines.append(_format_dataset_detail(full))
        else:
            lines.append(f"  - {_dataset_heading(full)}")
    if not datasets:
        lines.append("  - (none you can access)")
    if hidden := info.get("inaccessible_dataset_count"):
        lines.append(
            f"  - {hidden} other dataset(s) on this dashboard are not "
            "accessible to this user."
        )
    return "\n".join(lines)


def _describe_context_item(
    key: str,
    identifier: Any,
    tools_by_name: dict[str, Any],
    detailed: bool,
) -> str:
    """Describe one context entry (dashboard/chart/dataset) as a list item.

    ``detailed`` (first turn) includes column/metric detail; otherwise only the
    identity of each dataset is given. Falls back to the bare id when a lookup
    fails or the user may not see the resource.
    """
    tool_name, label = _CONTEXT_INFO_TOOLS[key]
    tool = tools_by_name.get(tool_name)
    info = _cached_resource_info(tool, identifier) if tool else None
    if not isinstance(info, dict):
        return f"- Current {label}: ID {identifier}"

    if key == "dashboard_id" and "datasets" in info:
        return _describe_dashboard(
            identifier, info, tools_by_name.get("get_dataset_info"), detailed
        )

    if key == "dataset_id":
        if detailed:
            return "- Current dataset:\n" + _format_dataset_detail(info)
        return f"- Current dataset: {_dataset_heading(info)}"

    if not detailed:
        return f"- Current {label}: ID {identifier}"
    summary = json.dumps(info, default=str)
    if len(summary) > _MAX_GENERIC_INFO_CHARS:
        summary = summary[:_MAX_GENERIC_INFO_CHARS] + "…(truncated)"
    return f"- Current {label} (ID {identifier}): {summary}"


def _build_context_block(context: dict[str, Any], detailed: bool = True) -> str:
    """Build a compact, resolved description of what the user is viewing.

    For each id present in ``context`` (dashboard/chart/dataset), resolves it
    through the in-process MCP discovery tools (as the user, so only resources
    they may see are described) and inlines a summary. For a dashboard this is
    the datasets behind its charts, so the agent can pick the dataset and query
    it without discovery round-trips. ``detailed`` adds columns, metrics and
    descriptions; follow-up turns use the short form. Falls back to the bare id
    if a lookup fails or a tool is unavailable.
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

    lines = [
        _describe_context_item(key, identifier, tools_by_name, detailed)
        for key, identifier in present
    ]
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


# Human-friendly status labels for MCP tools, surfaced in the streaming trace
# (see invoke_agent_stream) instead of raw tool names. Deliberately
# non-exhaustive: any tool not listed here still gets a readable label via
# _tool_label's fallback humanization.
_TOOL_FRIENDLY_LABELS: dict[str, str] = {
    "list_charts": "Looking through your charts",
    "list_dashboards": "Looking through your dashboards",
    "list_datasets": "Checking available datasets",
    "get_chart_info": "Reading chart details",
    "get_chart_data": "Pulling chart data",
    "get_dashboard_info": "Reading dashboard details",
    "get_dataset_info": "Inspecting dataset schema",
    "generate_chart": "Building the chart",
    "update_chart": "Updating the chart",
    "generate_dashboard": "Assembling the dashboard",
    "execute_sql": "Running the SQL query",
    "generate_explore_link": "Preparing a chart link",
    "get_instance_info": "Gathering Superset info",
    "health_check": "Checking system health",
}


def _tool_label(tool_name: str) -> str:
    """Human-readable status label for a tool name, for the streaming trace."""
    return (
        _TOOL_FRIENDLY_LABELS.get(tool_name) or tool_name.replace("_", " ").capitalize()
    )


# Caps for the per-turn tool trail stored with each answer (see
# conversation.TOOL_TRAIL_ROLE): enough to keep resolved ids and the working
# queries, small enough to replay cheaply.
_TRAIL_ARGS_MAX_CHARS = 600
_TRAIL_ERROR_MAX_CHARS = 200
_TRAIL_MAX_CHARS = 3000


def _is_tool_error(content: Any) -> bool:
    """Tool wrappers report failures as text starting with ❌."""
    return _content_to_text(content).lstrip().startswith("❌")


def _format_tool_trail(calls: list[dict[str, Any]]) -> str:
    """Render a turn's tool calls as a compact list for the next turns.

    Each entry gives the tool, its arguments and whether it succeeded (with the
    start of the error if not), so a follow-up can reuse resolved datasets and
    working queries and avoid repeating failed ones. When over budget the
    earliest calls are dropped, since later ones are usually the ones that
    worked.
    """
    lines = []
    for call in calls:
        if not call.get("name"):
            continue
        args = call.get("args")
        args_text = args if isinstance(args, str) else json.dumps(args, default=str)
        line = f"- {call['name']} {_clip(args_text or '{}', _TRAIL_ARGS_MAX_CHARS)}"
        status = call.get("status")
        if status == "error":
            line += " -> error"
            if call.get("error"):
                line += f": {_clip(call['error'], _TRAIL_ERROR_MAX_CHARS)}"
        elif status == "ok":
            line += " -> ok"
        lines.append(line)

    omitted = False
    while lines and len("\n".join(lines)) > _TRAIL_MAX_CHARS:
        lines.pop(0)
        omitted = True
    if omitted:
        lines.insert(0, "- (earlier calls omitted)")
    return "\n".join(lines)


def _tool_calls_from_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Collect tool calls and their outcomes from a finished agent run."""
    calls: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            if (call := calls.get(msg.tool_call_id)) is not None:
                failed = _is_tool_error(msg.content)
                call["status"] = "error" if failed else "ok"
                if failed:
                    call["error"] = _content_to_text(msg.content)
            continue
        for tool_call in getattr(msg, "tool_calls", None) or []:
            if tool_call.get("id"):
                calls[tool_call["id"]] = {
                    "name": tool_call.get("name") or "",
                    "args": tool_call.get("args") or {},
                }
    return list(calls.values())


def _record_answer(
    conversation_history: Any | None, answer: str, calls: list[dict[str, Any]]
) -> None:
    """Store the answer and, if any tools ran, the trail behind it."""
    if not conversation_history:
        return
    conversation_history.add_message("assistant", answer)
    if trail := _format_tool_trail(calls):
        conversation_history.add_message(TOOL_TRAIL_ROLE, trail)


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
    if name := _current_user_display_name():
        parts.append(f"[User] {name}")
    if context:
        context_block = _build_context_block(context)
        if context_block:
            parts.append(f"[Context]\n{context_block}")
    return "\n\n".join(parts)


def _compact_context_line(context: dict[str, Any]) -> str:
    """Short current-view reminder for follow-up turns.

    Keeps the current view, and for a dashboard its datasets (id, name,
    location, and what a virtual one reads), in front of the agent after the
    first turn's detailed block scrolls out of the replayed history window. The
    lookups are in-process and briefly cached; no model round-trip.
    """
    return _build_context_block(context, detailed=False)


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
        usage = _new_usage_totals()
        for msg in response_messages[len(messages) :]:
            _add_usage(usage, getattr(msg, "usage_metadata", None))
        _log_usage(usage)
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

        # Record the answer, and the tool calls behind it, in history
        _record_answer(
            conversation_history,
            final_message,
            _tool_calls_from_messages(response_messages[len(messages) :]),
        )

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


class _StreamedTurn:
    """Track one streamed turn: answer text segments and tool calls.

    The ``on_*`` methods take stream chunks and yield the events to send on.
    Text is split at tool calls: the model often writes a short note before
    calling a tool, and each model call's text must not run into the next
    one's ("…available.The dashboard…"), on screen or in the stored answer.
    Tool calls are collected for the stored trail; their args stream as JSON
    fragments, and continuation chunks may carry only the call's index.
    """

    def __init__(self) -> None:
        self._segments: list[list[str]] = [[]]
        self._tool_ran_since_text = False
        # call id -> {"name", "args", "status", "error"}
        self._calls: dict[str, dict[str, Any]] = {}
        # index -> call id, for the current model call only
        self._call_id_by_index: dict[Any, str] = {}

    def on_tool_call_chunk(self, tool_call_chunk: Any) -> Iterator[tuple[str, Any]]:
        tc_id = tool_call_chunk.get("id")
        tc_name = tool_call_chunk.get("name")
        tc_index = tool_call_chunk.get("index")
        if tc_id:
            self._call_id_by_index[tc_index] = tc_id
        else:
            tc_id = self._call_id_by_index.get(tc_index)
        if not tc_id:
            return
        is_new = tc_id not in self._calls
        call = self._calls.setdefault(tc_id, {"name": "", "args": ""})
        if tc_name and not call["name"]:
            call["name"] = tc_name
        call["args"] += tool_call_chunk.get("args") or ""
        # Announce each call once, as soon as its name is known.
        if is_new and tc_name:
            yield (
                "trace_step",
                {
                    "id": tc_id,
                    "tool": tc_name,
                    "label": _tool_label(tc_name),
                    "status": "running",
                },
            )

    def on_text(self, delta: str) -> Iterator[tuple[str, Any]]:
        if not delta:
            return
        if self._tool_ran_since_text:
            self._tool_ran_since_text = False
            if any(self._segments):
                yield ("token", "\n\n")
            self._segments.append([])
        self._segments[-1].append(delta)
        yield ("token", delta)

    def on_tool_result(self, message: ToolMessage) -> Iterator[tuple[str, Any]]:
        self._tool_ran_since_text = True
        # The next model call numbers its tool calls from 0 again.
        self._call_id_by_index = {}
        tool_name = message.name or ""
        failed = _is_tool_error(message.content)
        if (call := self._calls.get(message.tool_call_id)) is not None:
            call["status"] = "error" if failed else "ok"
            if failed:
                call["error"] = _content_to_text(message.content)
        yield (
            "trace_step",
            {
                "id": message.tool_call_id,
                "tool": tool_name,
                "label": _tool_label(tool_name),
                "status": "error" if failed else "done",
            },
        )

    def answer(self) -> str:
        """The full answer, with text from separate model calls apart."""
        return (
            "\n\n".join("".join(part) for part in self._segments if part)
            or "No response from agent"
        )

    def calls(self) -> list[dict[str, Any]]:
        return list(self._calls.values())


def invoke_agent_stream(
    query: str,
    context: dict[str, Any] | None = None,
    conversation_history: Any | None = None,
) -> Any:
    """Stream the agent's response as it is generated.

    Yields ``(event_type, payload)`` tuples so the transport layer can frame
    them (e.g. as SSE):
      - ("token", str)  — an incremental chunk of the assistant's answer
      - ("trace_step", dict) — a tool call started/finished:
        ``{"id", "tool", "label", "status": "running"|"done"|"error"}``.
        Carries only a human-readable label and status, never tool
        args/results, so it's safe to stream straight to the client.
      - ("done", dict)  — final event with `conversation_id` + `verification_note`
      - ("error", str)  — an error occurred mid-stream

    Mirrors `invoke_agent`'s preparation (context enrichment, history recording,
    windowed history) but replaces the blocking `.invoke()` with LangGraph's
    token streaming, and records the full accumulated answer at the end.
    """
    usage = _new_usage_totals()
    try:
        agent = create_superset_agent()
        messages = _prepare_messages(query, context, conversation_history)

        logger.info(
            "Streaming agent with %s messages (conversation: %s)",
            len(messages),
            conversation_history.conversation_id if conversation_history else "none",
        )

        turn = _StreamedTurn()
        # stream_mode="messages" yields (message_chunk, metadata) tuples: text
        # deltas arrive as AIMessageChunk, and completed tool calls arrive as
        # ToolMessage once the tool has run.
        for chunk, _metadata in agent.stream(
            {"messages": messages}, stream_mode="messages"
        ):
            if isinstance(chunk, AIMessageChunk):
                _add_usage(usage, chunk.usage_metadata)
                for tool_call_chunk in chunk.tool_call_chunks or []:
                    yield from turn.on_tool_call_chunk(tool_call_chunk)
                yield from turn.on_text(_content_to_text(chunk.content))
            elif isinstance(chunk, ToolMessage):
                yield from turn.on_tool_result(chunk)

        logger.info("✅ Agent stream completed: %s...", query[:60])

        _record_answer(conversation_history, turn.answer(), turn.calls())

        done: dict[str, Any] = {"verification_note": _verification_note(query)}
        if conversation_history:
            done["conversation_id"] = conversation_history.conversation_id
        yield ("done", done)

    except Exception as e:
        logger.error("Agent stream failed: %s", str(e), exc_info=True)
        yield ("error", str(e))
    finally:
        # Tokens spent before a mid-stream failure are billed too.
        _log_usage(usage)


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
