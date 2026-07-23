# MCP Troubleshooting

> **Original sources:**
> [`superset/mcp_service/MCP_TOOL_FIX_QUICKREF.md`](../../../superset/mcp_service/MCP_TOOL_FIX_QUICKREF.md) ·
> [`superset/mcp_service/MCP_MAINTENANCE_GUIDE.md`](../../../superset/mcp_service/MCP_MAINTENANCE_GUIDE.md) ·
> [`superset/mcp_service/MCP_FIX_EXPLANATION.md`](../../../superset/mcp_service/MCP_FIX_EXPLANATION.md) ·
> [`superset/mcp_service/MCP_TOOL_FAILURE_ANALYSIS.md`](../../../superset/mcp_service/MCP_TOOL_FAILURE_ANALYSIS.md)

---

## Quick Diagnostics

```bash
# 1. Are tools loading?
docker compose logs superset | grep -E "Loaded.*MCP|mcp_client"

# 2. Is the AI endpoint up?
curl -f http://localhost:8088/api/v1/ai/health

# 3. Recent errors in the AI assistant
docker compose logs superset | grep -E "ERROR|CRITICAL" | grep -i "ai\|mcp\|agent"

# 4. Python environment inside the container
docker compose exec superset python -c "
import superset.mcp_service.app as m
print('Tools registered:', list(m.mcp._tool_manager._tools.keys()))
"
```

---

## Known Errors & Fixes

### `ValidationError: 'big_number_total' is not a valid discriminator tag`

**Trigger:** LLM passes `chart_type = "big_number"` to `generate_chart`.

**Root cause:** `ChartConfig` discriminated union only included `"xy"` and
`"table"` tags.

**Fix:** `BigNumberChartConfig` added to
[`superset/mcp_service/chart/schemas.py`](../../../superset/mcp_service/chart/schemas.py)
with `chart_type: Literal["big_number"]`.

**Verify:**

```python
from superset.mcp_service.chart.schemas import ChartConfig
cfg = ChartConfig.model_validate({"chart_type": "big_number", "metric": {"column": "revenue", "aggregate": "SUM"}})
print(cfg)   # should not raise
```

---

### `sqlalchemy.exc.InvalidRequestError: Object '<User …>' is already attached to session N (this is M)`

**Trigger:** MCP tool call executes after a previous `asyncio.run()` already
closed its scoped session.

**Root cause:** Each `asyncio.run()` creates a new SQLAlchemy scoped session.
The `User` object was bound to the previous session.

**Fix:** In
[`superset/mcp_service/auth.py`](../../../superset/mcp_service/auth.py):

```python
from superset.extensions import db
try:
    user = db.session.merge(user)
except Exception as merge_err:
    logger.debug("Could not merge user into current session: %s", merge_err)
```

---

### `RuntimeWarning: coroutine 'FastMCP.get_tools' was never awaited`

**Trigger:** Tool loading path calls `mcp.get_tools()` as if it were
synchronous.

**Root cause:** `FastMCP.get_tools()` is a coroutine; calling it without
`await` returns a coroutine object that is immediately discarded.

**Fix:** In
[`superset/mcp_service/app.py`](../../../superset/mcp_service/app.py):
detect the coroutine object and close it before it triggers the warning.

```python
result = mcp.get_tools()
if hasattr(result, "__await__"):
    result.close()   # prevent "was never awaited" RuntimeWarning
    result = mcp._tool_manager._tools
```

---

### `DetachedInstanceError: Instance '<User …>' is not bound to a Session`

**Trigger:** `g.user.roles` accessed inside a tool after the request context
that loaded the user has expired.

**Fix:** Catch and re-query in
[`superset/mcp_service/auth.py`](../../../superset/mcp_service/auth.py):

```python
try:
    roles = user.roles
except DetachedInstanceError:
    user = db.session.get(User, user.id)
    roles = user.roles if user else []
```

---

### `RuntimeError: No active context found` / `RuntimeError: session is not available`

**Trigger:** FastMCP's `@parse_request` decorator calls `get_context()`, which
requires an active MCP WebSocket session.

**Root cause:** Tools are called in-process without a real MCP session.

**Fix:** `SessionlessContext` in
[`superset/ai_assistant/mcp_client.py`](../../../superset/ai_assistant/mcp_client.py)
— a stub that satisfies the `Context` interface and routes all logging to the
Python standard logger.

---

### `ImportError: cannot import name 'create_react_agent' from 'langchain.agents'`

**Trigger:** Attempting to import from `langchain.agents`.

**Root cause:** In the installed version, `create_react_agent` lives in
`langgraph.prebuilt`, not `langchain.agents`.

**Fix:** In
[`superset/ai_assistant/agent.py`](../../../superset/ai_assistant/agent.py):

```python
from langgraph.prebuilt import create_react_agent   # correct
# NOT: from langchain.agents import create_react_agent
```

---

### `TypeError: list_datasets() missing 1 required positional argument: 'request'`

**Trigger:** Tool invocation unpacks kwargs instead of passing a Pydantic
model instance.

**Root cause:** FastMCP tool functions expect their first argument to be the
full request model, not keyword-unpacked fields.

**Fix:**

```python
# Correct
result = await tool_callable(request_obj)   # single positional Pydantic model

# Wrong
result = await tool_callable(**kwargs)
```

---

### 404 on `/api/v1/ai/chat`

**Possible causes:**

1. Blueprint not registered — check `superset/__init__.py` for
   `register_blueprint(ai_assistant_bp, ...)`.
2. Wrong URL — no trailing slash on `/api/v1/ai/chat`.
3. Worker crashed on startup — check `docker compose logs superset` for import
   errors.

---

## Log Patterns to Watch

| Pattern | Meaning |
|---------|---------|
| `Loaded 19 MCP tools` | Healthy startup |
| `Loaded 0 MCP tools` | Tool registration failed; check import errors |
| `Could not merge user into current session` | Session cross-contamination (non-fatal, logged at DEBUG) |
| `coroutine.*never awaited` | `RuntimeWarning` — `result.close()` fix may not be applied |
| `ValidationError.*not a valid discriminator` | Unsupported `chart_type` value from LLM |
| `DetachedInstanceError` | User object not re-merged before tool call |
| `LangGraphDeprecatedSinceV10` | LangGraph v1 warning — safe to ignore; tracked separately |
