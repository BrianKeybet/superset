# MCP Integration

> **Original sources:**
> [`superset/mcp_service/MCP_FIX_SUMMARY_FINAL.md`](../../../superset/mcp_service/MCP_FIX_SUMMARY_FINAL.md) ·
> [`superset/ai_assistant/MCP_INTEGRATION.md`](../../../superset/ai_assistant/MCP_INTEGRATION.md) ·
> [`superset/ai_assistant/MCP_MIGRATION_SUMMARY.md`](../../../superset/ai_assistant/MCP_MIGRATION_SUMMARY.md)

---

## How the Agent Discovers Tools

Tools are loaded **in-process** — the agent imports the FastMCP singleton
directly from the MCP service, with no HTTP calls:

```python
# superset/ai_assistant/mcp_client.py
from superset.mcp_service.app import mcp   # FastMCP instance, already
                                            # registered with all tools
tools_dict = mcp._tool_manager._tools      # {name: FastMCPTool, ...}
```

This replaces an earlier design that called `http://superset:8088/mcp/` and
relied on URL routing.  The in-process approach avoids network latency,
authentication round-trips, and URL-trailing-slash bugs.

---

## Tool Invocation Flow

```
Agent.invoke()
  └─ Tool.run("list datasets")
       └─ mcp_client._make_tool_func(name, tool)
            ├─ Build JSON payload: {"name": ..., "arguments": {...}}
            ├─ Parse to Pydantic request model via tool._tool.fn.__annotations__
            ├─ _setup_user_context()   ← binds g.user, sets Flask app context
            │    └─ db.session.merge(user)  ← avoids cross-session error
            ├─ set_context(SessionlessContext)  ← satisfies @parse_request
            └─ asyncio.run(tool_callable(request_obj))
```

---

## `mcp_client.py` Design

### Authentication hook (`mcp_auth_hook`)

Before every tool call, `mcp_auth_hook` pushes a Flask application context and
binds the current logged-in user to the request/app context so that
`security_manager.can_access(...)` checks pass as the correct user.

```python
def mcp_auth_hook():
    from flask import g
    from superset import security_manager
    user = get_current_user()           # reads from outer scope
    g.user = user
    security_manager.set_user(user)
```

### `SessionlessContext`

FastMCP's `@parse_request` decorator calls `get_context()` which normally
requires an active MCP WebSocket session. `SessionlessContext` satisfies this
interface without a real session:

```python
class SessionlessContext(Context):
    async def log(self, level, message, **kwargs):
        logger.log(level_map[level], "[MCP] %s", message)   # route to stdlib

    # All other context methods are no-ops or empty stubs
```

The context is injected via `set_context(SessionlessContext(...))` before each
`asyncio.run()` call.

### Positional-argument wrapper

FastMCP tools expect a single Pydantic model instance as their first positional
argument (not keyword-unpacked kwargs):

```python
# Correct
result = await tool_callable(request_obj)

# Wrong — raises "missing 1 required positional argument"
result = await tool_callable(**kwargs)
```

---

## Tool Registration (`superset/mcp_service/`)

Each tool is registered in `app.py` with `@mcp.tool()`:

```python
# superset/mcp_service/app.py
from superset.mcp_service.chart.tool.generate_chart import generate_chart
from superset.mcp_service.dataset.tool.list_datasets import list_datasets
# ... etc.

mcp = FastMCP("superset")

@mcp.tool()
async def generate_chart_tool(...):
    return await generate_chart(...)
```

All 19 registered tools are listed in the master
[README](../README.md#mcp-tools).

---

## Pydantic Request Schemas

Every tool's input is validated by a Pydantic model defined in
`superset/mcp_service/<domain>/schemas.py`.

`ChartConfig` uses a **discriminated union** on `chart_type`:

```python
ChartConfig = Annotated[
    XYChartConfig | TableChartConfig | BigNumberChartConfig,
    Field(discriminator="chart_type"),
]
```

When adding a new chart type, add:

1. A new `*ChartConfig` class with `chart_type: Literal["<new_type>"]`.
2. Include it in the `ChartConfig` union.
3. Add a `map_*_config()` function in `chart_utils.py`.
4. Handle the new type in `map_config_to_form_data()`, `generate_chart_name()`,
   and `analyze_chart_capabilities()`.
