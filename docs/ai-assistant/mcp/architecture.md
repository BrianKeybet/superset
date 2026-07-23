# MCP Architecture

> **Original source (authoritative):**
> [`superset/mcp_service/ARCHITECTURE.md`](../../../superset/mcp_service/ARCHITECTURE.md)
> — 693 lines with full sequence diagrams, multi-instance deployment
> considerations, and connection-pool tuning.  Read it directly for the
> complete picture; this file is a navigational summary.

---

## High-Level Overview

```
Browser / API client
        │  POST /api/v1/ai/chat
        ▼
  Flask (superset worker)
        │
        ├─ ai_assistant blueprint  →  invoke_agent()
        │                               │
        │                               ├─ LangGraph ReAct loop
        │                               │
        │                               └─ mcp_client.get_mcp_tools()
        │                                       │  in-process import
        │                                       ▼
        └─ mcp_service (same process)   FastMCP._tool_manager._tools
```

The MCP service and AI assistant **share the same Gunicorn/Flask worker
process**. There is no MCP HTTP server involved at runtime for AI assistant
requests.

---

## Flask Singleton Pattern

`superset/mcp_service/app.py` creates a single `FastMCP` instance at module
import time:

```python
mcp = FastMCP("superset")
```

All `@mcp.tool()` registrations happen at import time. Once the module is
imported (which happens when the worker starts), the `mcp` object is a stable
singleton for the lifetime of the process.

---

## Multi-Instance / Kubernetes Deployment

Because conversation history is in-memory, multi-worker deployments must pin
sessions to a single worker (sticky sessions / consistent hashing). See
[ARCHITECTURE.md §Scaling](../../../superset/mcp_service/ARCHITECTURE.md) for
detailed guidance including Redis-backed history as the recommended upgrade
path.

---

## Request Isolation

Each AI chat request runs inside:
1. A Gunicorn worker (shared process).
2. `asyncio.run()` for each tool call — creates its own event loop.
3. SQLAlchemy scoped session (per `asyncio.run()` invocation).

Because `asyncio.run()` creates a *new* scoped session, any SQLAlchemy object
(e.g. `User`) loaded before the tool call must be re-merged:

```python
user = db.session.merge(user)   # auth.py — avoids "attached to session N (this is M)"
```

---

## Connection Pooling

Superset uses `NullPool` in async contexts and `QueuePool` for synchronous
workers.  The MCP tools execute synchronously via `asyncio.run()` so they
benefit from the existing `QueuePool`.  See
[ARCHITECTURE.md §Connection Pool Tuning](../../../superset/mcp_service/ARCHITECTURE.md)
for recommended `SQLALCHEMY_POOL_SIZE` values under load.

---

## Security Boundary

The MCP service has its own RBAC layer on top of Flask-AppBuilder's RBAC. See
[`superset/mcp_service/SECURITY.md`](../../../superset/mcp_service/SECURITY.md)
(803 lines) for the full threat model, token scoping, and audit-log design.
