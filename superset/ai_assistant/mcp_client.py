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
"""MCP (Model Context Protocol) client for connecting to Superset MCP service.

This module provides a wrapper to connect to Superset's native MCP service,
discover available tools, and convert them to LangChain-compatible tools.

The MCP service runs on localhost:5008 and provides tools for:
- Dashboard management (list, create, update)
- Chart management (list, create, preview, data)
- Dataset management (list, query schema)
- SQL Lab integration (execute queries)
- System metadata (instance info, health checks)
"""

import asyncio
import logging
import os
from typing import Any, Callable, Optional

import requests
from langchain_core.tools import Tool

from superset.utils import json

logger = logging.getLogger(__name__)

# Default MCP service configuration
# In Docker, use service name "superset-mcp"; locally, use "localhost"
# Can be overridden via MCP_SERVICE_HOST environment variable
DEFAULT_MCP_HOST = os.getenv("MCP_SERVICE_HOST", "localhost")
DEFAULT_MCP_PORT = int(os.getenv("MCP_SERVICE_PORT", "5008"))
DEFAULT_MCP_TIMEOUT = 30


class MCPClientError(Exception):
    """Raised when MCP client encounters an error."""

    pass


class SupersetMCPClient:
    """
    HTTP-based client for the Superset MCP service.

    The Superset MCP service exposes tools via a JSON-RPC interface.
    This client communicates with that service to discover and invoke tools.

    Attributes:
        base_url: Base URL of the MCP service (e.g., http://localhost:5008)
        timeout: Request timeout in seconds
    """

    def __init__(
        self,
        host: str = DEFAULT_MCP_HOST,
        port: int = DEFAULT_MCP_PORT,
        timeout: int = DEFAULT_MCP_TIMEOUT,
    ):
        """Initialize the MCP client.

        Args:
            host: MCP service host (default: localhost)
            port: MCP service port (default: 5008)
            timeout: Request timeout in seconds (default: 30)

        Raises:
            MCPClientError: If MCP service is not accessible
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        # ✅ CRITICAL FIX: Add trailing slash for correct urljoin behavior
        # The base URL must end in "/" — otherwise urljoin() drops the
        # "/mcp" path segment when resolving tool endpoints.
        self.base_url = f"http://{host}:{port}/mcp/"

        logger.debug(
            "🔌 MCP Client initialized: base_url=%s, host=%s, port=%s",
            self.base_url,
            host,
            port,
        )

        # Verify MCP service is accessible
        if not self._is_service_available():
            logger.error(
                "❌ MCP service not accessible at %s. "
                "Verify the following:\n"
                "  1. MCP service container is running: docker ps | grep mcp\n"
                "  2. Port %s is exposed: docker port <mcp-container>\n"
                "  3. Hostname '%s' resolves correctly in your environment\n"
                "  4. Service /health endpoint is accessible: "
                "curl http://%s:%s/health\n"
                "  5. Service /mcp/tools endpoint is accessible: "
                "curl http://%s:%s/mcp/tools\n"
                "  6. If using docker compose: docker compose --profile mcp up -d",
                self.base_url,
                port,
                host,
                host,
                port,
                host,
                port,
            )

    def _is_service_available(self) -> bool:
        """Check if MCP service is accessible."""
        try:
            # Health check at root level, not under /mcp path
            response = requests.get(
                f"http://{self.host}:{self.port}/health",
                timeout=5,
            )
            return response.status_code == 200
        except (requests.RequestException, Exception) as e:
            logger.debug("MCP service health check failed: %s", e)
            return False

    def call_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call an MCP tool and return its result with enhanced logging.

        Args:
            tool_name: Name of the MCP tool to call
            tool_input: Dictionary of tool arguments

        Returns:
            Tool result as dictionary with 'content' and optional 'error' keys

        Raises:
            MCPClientError: If tool call fails
        """
        try:
            if logger.isEnabledFor(logging.DEBUG):
                serialized_input = json.dumps(tool_input, default=str)
                logger.debug(
                    "🔧 MCP Tool Call: %s | Input: %s%s",
                    tool_name,
                    serialized_input[:200],
                    "..." if len(serialized_input) > 200 else "",
                )

            # ✅ CRITICAL FIX: Use direct URL construction to avoid urljoin issues
            url = f"{self.base_url}tools/{tool_name}"

            response = requests.post(
                url,
                json=tool_input,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code == 404:
                # Tool not found, try JSON-RPC endpoint
                return self._call_tool_jsonrpc(tool_name, tool_input)

            response.raise_for_status()

            result = response.json()

            if logger.isEnabledFor(logging.DEBUG):
                serialized_result = json.dumps(result, default=str)
                logger.debug(
                    "✅ MCP Tool Result (%s): %s%s",
                    tool_name,
                    serialized_result[:300],
                    "..." if len(serialized_result) > 300 else "",
                )

            return {
                "content": result.get("content") or json.dumps(result),
                "error": result.get("error"),
            }

        except requests.RequestException as e:
            error_msg = f"MCP tool call failed: {str(e)}"
            logger.error("❌ %s", error_msg)
            raise MCPClientError(error_msg) from e
        except Exception as e:
            error_msg = f"Unexpected error calling MCP tool {tool_name}: {str(e)}"
            logger.error("❌ %s", error_msg, exc_info=True)
            raise MCPClientError(error_msg) from e

    def _call_tool_jsonrpc(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call an MCP tool via JSON-RPC endpoint.

        Args:
            tool_name: Name of the MCP tool
            tool_input: Tool arguments

        Returns:
            Tool result dictionary
        """
        try:
            # ✅ CRITICAL FIX: Use direct URL construction to avoid urljoin issues
            url = f"{self.base_url}rpc"

            payload = {
                "jsonrpc": "2.0",
                "method": tool_name,
                "params": tool_input,
                "id": 1,
            }

            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )

            response.raise_for_status()
            result = response.json()

            if "error" in result:
                raise MCPClientError(result["error"].get("message", "Unknown error"))

            return {
                "content": json.dumps(result.get("result", result)),
                "error": None,
            }

        except Exception as e:
            logger.error("JSON-RPC call to %s failed: %s", tool_name, e)
            raise MCPClientError(f"JSON-RPC call failed: {str(e)}") from e

    def list_tools(self) -> list[dict[str, Any]]:
        """
        List available tools from the MCP service.

        Returns:
            List of tool definitions with name, description, and input schema

        Raises:
            MCPClientError: If unable to retrieve tools
        """
        try:
            # ✅ CRITICAL FIX: Direct URL construction to avoid urljoin issues
            # urljoin has ambiguous behavior with trailing slashes
            url = f"{self.base_url}tools"
            logger.debug("📋 Fetching MCP tools from: %s", url)

            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()

            tools = response.json()
            tool_names = [t.get("name") for t in tools]
            logger.info(
                "✅ Discovered %s tools from MCP service: %s%s",
                len(tools),
                tool_names[:5],
                "..." if len(tool_names) > 5 else "",
            )
            return tools

        except requests.exceptions.ConnectionError as e:
            logger.error(
                "❌ Cannot connect to MCP service at %s: %s. "
                "Ensure MCP service is running and accessible.",
                self.base_url,
                e,
            )
            raise MCPClientError(f"MCP service connection failed: {str(e)}") from e
        except requests.exceptions.HTTPError as e:
            logger.error(
                "❌ MCP service returned HTTP error: %s %s",
                e.response.status_code,
                e.response.reason,
            )
            logger.error("   URL attempted: %s", e.response.url)
            logger.error("   Response body: %s", e.response.text[:200])
            raise MCPClientError(
                f"Failed to list tools: HTTP {e.response.status_code}"
            ) from e
        except Exception as e:
            logger.error("❌ Unexpected error fetching MCP tools: %s", e, exc_info=True)
            raise MCPClientError(f"Failed to list tools: {str(e)}") from e

    def get_tool_definition(self, tool_name: str) -> Optional[dict[str, Any]]:
        """
        Get definition of a specific MCP tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool definition with name, description, and input schema, or None

        Raises:
            MCPClientError: If unable to retrieve tool definition
        """
        try:
            tools = self.list_tools()
            for tool in tools:
                if tool.get("name") == tool_name:
                    return tool
            return None
        except MCPClientError:
            raise
        except Exception as e:
            logger.error("Failed to get tool definition for %s: %s", tool_name, e)
            raise MCPClientError(f"Failed to get tool definition: {str(e)}") from e


def create_mcp_langchain_tool(
    mcp_client: SupersetMCPClient,
    tool_name: str,
    tool_definition: dict[str, Any],
) -> Tool:
    """
    Convert an MCP tool to a LangChain-compatible Tool via HTTP.

    Args:
        mcp_client: SupersetMCPClient HTTP instance
        tool_name: Name of the tool
        tool_definition: Tool definition from MCP service

    Returns:
        LangChain Tool instance
    """

    def tool_func(*args: Any, **kwargs: Any) -> str:
        """Wrapper function for MCP tool invocation via HTTP.

        Handles both positional and keyword arguments as LangChain may pass
        tool input as either a dict argument or as kwargs.
        """
        # Handle LangChain's calling convention
        if args and len(args) > 0:
            if isinstance(args[0], dict):
                # Tool input passed as dict (standard LangChain behavior)
                kwargs = {**args[0], **kwargs}
            else:
                # Single positional argument - treat as input
                kwargs = {"input": args[0]}

        write_ops = {
            "create_chart",
            "update_chart",
            "update_chart_preview",
            "add_chart_to_dashboard",
            "generate_dashboard",
            "generate_chart",
            "generate_explore_link",
        }
        is_write_op = tool_name in write_ops

        try:
            if is_write_op:
                logger.info("📝 [WRITE] Calling %s with args: %s", tool_name, kwargs)
            else:
                logger.debug("📖 [READ] Calling %s", tool_name)

            result = mcp_client.call_tool(tool_name, kwargs)

            if result.get("error"):
                error_msg = result.get("error", "Unknown error")
                logger.warning("❌ Tool %s returned error: %s", tool_name, error_msg)
                return f"❌ Error: {error_msg}"

            content = result.get("content", "No result")

            if is_write_op:
                logger.info("✅ [WRITE] %s completed.", tool_name)
                content_lower = str(content).lower()
                if any(
                    word in content_lower for word in ["mock", "demo", "fake", "test"]
                ):
                    logger.warning(
                        "⚠️  Tool %s response may contain test/mock data",
                        tool_name,
                    )

            return content

        except MCPClientError as e:
            logger.error("❌ Tool %s execution failed: %s", tool_name, str(e))
            return f"❌ Tool execution failed: {str(e)}"
        except Exception as e:
            logger.error(
                "❌ Unexpected error in tool %s: %s", tool_name, e, exc_info=True
            )
            return f"❌ Unexpected error: {str(e)}"

    description = tool_definition.get("description", f"MCP tool: {tool_name}")

    return Tool(
        name=tool_name,
        func=tool_func,
        description=description,
        args_schema=None,
    )


# Module-level cache. MCP tool discovery + wrapping is expensive but the result
# is stable for the process lifetime, so build it once and reuse across requests.
_cached_mcp_tools: Optional[list[Tool]] = None


def get_mcp_tools(
    host: str = DEFAULT_MCP_HOST,
    port: int = DEFAULT_MCP_PORT,
    tool_filter: Optional[list[str]] = None,
) -> list[Tool]:
    """
    Load MCP tools directly from the FastMCP instance (in-process).

    The wrapped tools are built once and cached at module level; subsequent
    calls return the cached list (optionally filtered by name). The wrappers
    resolve the Flask request context and current user at *call* time, so
    caching the tool objects does not leak per-user state.

    Args:
        host: Ignored (kept for backwards compatibility)
        port: Ignored (kept for backwards compatibility)
        tool_filter: Optional list of tool names to include.
            If None, all tools are included.

    Returns:
        List of LangChain Tool instances

    Example:
        >>> tools = get_mcp_tools()  # Get all MCP tools
        >>> tools = get_mcp_tools(tool_filter=["list_charts", "get_chart_info"])
    """
    global _cached_mcp_tools

    if _cached_mcp_tools is None:
        tools = _build_mcp_tools()
        if not tools:
            # Don't cache an empty result (e.g. a call racing app startup before
            # tools are registered) — leave the cache unset so the next call retries.
            return []
        _cached_mcp_tools = tools

    if tool_filter:
        return [tool for tool in _cached_mcp_tools if tool.name in tool_filter]
    return _cached_mcp_tools


def _build_mcp_tools() -> list[Tool]:  # noqa: C901
    """Discover and wrap all in-process FastMCP tools as LangChain tools.

    This is the expensive path (registration, registry introspection, wrapper
    construction). It runs once per process; callers go through the cached
    get_mcp_tools() instead of calling this directly.
    """
    try:
        logger.debug(
            "🔌 Loading MCP tools directly from FastMCP instance (in-process)..."
        )

        # Import the global FastMCP instance and helper functions
        from superset.mcp_service.app import (
            get_registered_mcp_tools,
            mcp as fastmcp_instance,
            register_all_tools,
        )
        from superset.mcp_service.flask_singleton import app as mcp_flask_app

        if not fastmcp_instance:
            logger.error("❌ Failed to load FastMCP instance.")
            return []

        logger.debug(
            "FastMCP instance type: %s (id: %s)",
            type(fastmcp_instance).__name__,
            id(fastmcp_instance),
        )

        # Ensure tools are registered (idempotent; module import already did this)
        register_all_tools()

        fastmcp_tools = get_registered_mcp_tools()

        if not fastmcp_tools:
            logger.error("❌ No tools found in FastMCP instance.")
            return []

        logger.debug(
            "📋 Found %s MCP tools (via direct in-process access)",
            len(fastmcp_tools),
        )

        # Helper function to create a FastMCP context using the proper API
        def create_fastmcp_context_manager() -> Any:
            """Create a context manager that sets up FastMCP context for tool execution.

            Subclasses Context to override the log() method so that ctx.info(),
            ctx.debug() etc. write to Python's logging instead of trying to send
            messages over an MCP session (which doesn't exist here).
            """
            from fastmcp.server.context import Context, set_context

            class SessionlessContext(Context):
                """Context that redirects MCP log messages to Python logging."""

                async def log(
                    self,
                    message: str,
                    level: str | None = None,
                    logger_name: str | None = None,
                    extra: dict[str, Any] | None = None,
                ) -> None:
                    log_level = (level or "info").lower()
                    log_fn = {
                        "debug": logger.debug,
                        "info": logger.info,
                        "notice": logger.info,
                        "warning": logger.warning,
                        "warn": logger.warning,
                        "error": logger.error,
                        "critical": logger.critical,
                        "alert": logger.critical,
                        "emergency": logger.critical,
                    }.get(log_level, logger.info)
                    log_fn("[MCP Tool] %s", message)

            context = SessionlessContext(fastmcp_instance)
            return set_context(context)

        # Convert FastMCP tools to LangChain tools
        langchain_tools = []
        for fastmcp_tool in fastmcp_tools:
            try:
                tool_name = fastmcp_tool.name

                # Create wrapper that handles Flask request context
                def make_tool_wrapper(  # noqa: C901
                    tool_obj: Any, flask_app: Any
                ) -> Callable[..., Any]:
                    """Create a wrapper with proper Flask request context."""

                    def tool_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: C901
                        """Call FastMCP tool with Flask request context."""
                        # Handle LangChain's positional argument convention
                        request_obj = None
                        if args and len(args) > 0:
                            if isinstance(args[0], dict):
                                request_obj = args[0]
                                kwargs = {**request_obj, **kwargs}
                            else:
                                request_obj = args[0]
                                kwargs = {"input": args[0]}

                        tool_name_inner = (
                            tool_obj.name
                            if hasattr(tool_obj, "name")
                            else str(tool_obj)
                        )

                        try:
                            logger.debug("📖 [CALL] Calling %s", tool_name_inner)

                            # Get the underlying tool function
                            if hasattr(tool_obj, "fn") and callable(tool_obj.fn):
                                tool_callable = tool_obj.fn
                            elif callable(tool_obj):
                                tool_callable = tool_obj
                            else:
                                return f"❌ Tool {tool_name_inner} not callable"

                            # Reuse the existing Flask request context if present,
                            # otherwise create one.
                            from flask import g, has_request_context

                            if has_request_context():
                                # Already inside a request context (API endpoint).
                                logger.debug(
                                    "Using existing Flask request context for %s",
                                    tool_name_inner,
                                )
                                if asyncio.iscoroutinefunction(tool_callable):
                                    # @parse_request tools take the request as the first
                                    # arg; needs a FastMCP context for logging.
                                    # and need FastMCP context for logging
                                    with create_fastmcp_context_manager():
                                        result = asyncio.run(
                                            tool_callable(request_obj or kwargs)
                                        )
                                else:
                                    with create_fastmcp_context_manager():
                                        result = tool_callable(request_obj or kwargs)
                            else:
                                # No request context — create a test one with proper
                                # auth setup.
                                logger.debug(
                                    "Creating test request context for %s",
                                    tool_name_inner,
                                )
                                with flask_app.test_request_context():
                                    # Set g.user so the auth wrapper can read
                                    # user.roles without an AnonymousUserMixin error.
                                    try:
                                        from flask_login import current_user

                                        g.user = current_user
                                    except Exception as exc:  # noqa: BLE001
                                        # Best-effort: some tools don't require auth.
                                        logger.debug(
                                            "Could not set g.user from session: %s",
                                            exc,
                                        )

                                    # Call the tool function with FastMCP context
                                    if asyncio.iscoroutinefunction(tool_callable):
                                        # @parse_request tools take the request as
                                        # the first positional arg (FastMCP context).
                                        # and need FastMCP context for logging
                                        with create_fastmcp_context_manager():
                                            result = asyncio.run(
                                                tool_callable(request_obj or kwargs)
                                            )
                                    else:
                                        with create_fastmcp_context_manager():
                                            result = tool_callable(
                                                request_obj or kwargs
                                            )

                            # Convert result to string
                            if isinstance(result, str):
                                return result
                            elif isinstance(result, dict):
                                return json.dumps(result)
                            else:
                                return str(result)

                        except Exception as e:
                            error_msg = (
                                f"Tool {tool_name_inner} execution failed: {str(e)}"
                            )
                            logger.error("❌ %s", error_msg, exc_info=True)
                            return f"❌ {error_msg}"

                    return tool_wrapper

                # Create the LangChain tool
                description = fastmcp_tool.description or f"MCP tool: {tool_name}"

                langchain_tool = Tool(
                    name=tool_name,
                    func=make_tool_wrapper(fastmcp_tool, mcp_flask_app),
                    description=description,
                    args_schema=None,
                )

                langchain_tools.append(langchain_tool)
                logger.debug("✅ Loaded MCP tool: %s", tool_name)

            except Exception as e:
                tool_name = getattr(fastmcp_tool, "name", "unknown")
                logger.warning(
                    "⚠️  Failed to load tool %s: %s",
                    tool_name,
                    e,
                    exc_info=True,
                )
                continue

        logger.info("✅ Loaded %s MCP tools (in-process)", len(langchain_tools))
        return langchain_tools

    except ImportError as e:
        logger.error("❌ Failed to import FastMCP: %s", e)
        return []
    except Exception as e:
        logger.error("Failed to load MCP tools: %s", e, exc_info=True)
        return []
