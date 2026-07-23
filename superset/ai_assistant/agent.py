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
from typing import Any

from langgraph.prebuilt import create_react_agent  # noqa: E402 - langgraph re-exports this

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langgraph")

from superset.ai_assistant.config import get_llm_instance
from superset.ai_assistant.mcp_client import get_mcp_tools

logger = logging.getLogger(__name__)

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


def create_superset_agent(tools: list[Any] | None = None) -> Any:
    """
    Create a LangChain agent using Superset's native MCP tools.

    This function creates a React agent that uses tools from Superset's MCP service.
    The MCP service must be running on localhost:5008 for tools to be available.

    Args:
        tools: Optional list of pre-configured tools. If None, tools are discovered
               from the MCP service automatically.

    Returns:
        Configured LangGraph agent instance

    Raises:
        ValueError: If LLM initialization fails (missing API keys)
    """
    try:
        llm = get_llm_instance()
    except ValueError as e:
        logger.error(f"Failed to initialize LLM: {e}")
        raise

    if tools is None:
        # Discover and load MCP tools from Superset service
        import os
        mcp_host = os.getenv("MCP_SERVICE_HOST", "localhost")
        mcp_port = os.getenv("MCP_SERVICE_PORT", "5008")
        
        logger.info(
            f"🔌 Discovering MCP tools from Superset MCP service at "
            f"{mcp_host}:{mcp_port}..."
        )
        tools = get_mcp_tools()

        if not tools:
            logger.error(
                f"❌ No MCP tools available. Agent will run without tools, "
                f"which severely limits capabilities.\n\n"
                f"To fix this, ensure:\n"
                f"  1. MCP service is running: docker compose --profile mcp up -d\n"
                f"  2. MCP service is accessible at {mcp_host}:{mcp_port}\n"
                f"  3. Check logs for MCP service errors\n"
                f"  4. Verify MCP container status: docker ps | grep mcp"
            )
            tools = []

    # Create a React agent using LangGraph
    # The agent will automatically select appropriate tools for each query
    agent = create_react_agent(
        llm,
        tools or [],
    )

    tool_names = [tool.name for tool in (tools or [])]
    if tool_names:
        logger.info(
            f"✅ Superset AI Agent initialized with {len(tool_names)} MCP tools: "
            f"{', '.join(tool_names[:5])}{'...' if len(tool_names) > 5 else ''}"
        )
    else:
        logger.error(
            f"❌ WARNING: Superset AI Agent created with 0 MCP tools. "
            f"The agent will not be able to access Superset data or perform operations."
        )
    return agent

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
        # Build the user message with optional context
        user_content = query
        if context:
            context_parts = []
            if context.get("dashboard_id"):
                context_parts.append(f"Current dashboard: ID {context['dashboard_id']}")
            if context.get("chart_id"):
                context_parts.append(f"Current chart: ID {context['chart_id']}")
            
            if context_parts:
                user_content = f"{query}\n\n[Context: {'; '.join(context_parts)}]"
        
        # Record user message in conversation history
        if conversation_history:
            conversation_history.add_message("user", user_content)
        
        # Build messages list with full conversation history
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add all previous messages from conversation history
        if conversation_history:
            messages.extend(conversation_history.get_conversation_context())
        
        # Add current user message
        messages.append({"role": "user", "content": user_content})
        
        logger.info(
            f"Invoking agent with {len(messages)} messages "
            f"(conversation: {conversation_history.conversation_id if conversation_history else 'none'})"
        )
        
        # Invoke the agent with the user query
        # LangGraph agents expect messages in a specific format
        response = agent.invoke(
            {
                "messages": messages,
            }
        )

        # Extract the final message from the agent response
        messages = response.get("messages", [])
        if not messages:
            final_message = "No response from agent"
        else:
            # Get the last message (agent's final response)
            last_msg = messages[-1]

            # Handle different message formats (dict vs AIMessage object)
            if isinstance(last_msg, dict):
                final_message = last_msg.get("content", "No response")
            else:
                # It's an AIMessage or similar object
                final_message = getattr(last_msg, "content", "No response")

        logger.info(f"✅ Agent query completed: {query[:60]}...")
        
        # Record assistant response in conversation history
        if conversation_history:
            conversation_history.add_message("assistant", final_message)
        
        # Add verification guidance to response
        verification_note = ""
        if any(word in query.lower() for word in ["create", "add", "chart", "dashboard"]):
            verification_note = "\n\n---\n⚠️  **Verification Tip**: This response indicates the operation succeeded according to MCP tools. However, if the new resource is not visible in Superset UI, please:\n1. Refresh the page\n2. Check the resource list again\n3. Report any missing resources — this may indicate a tool or API issue"
        
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