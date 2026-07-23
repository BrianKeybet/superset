# Backend Overview

> **Original sources:** [`AI_ASSISTANT_DELIVERY.md`](../../../AI_ASSISTANT_DELIVERY.md) ·
> [`superset/ai_assistant/README_MCP.md`](../../../superset/ai_assistant/README_MCP.md) ·
> [`superset/ai_assistant/MCP_QUICKSTART.md`](../../../superset/ai_assistant/MCP_QUICKSTART.md)

---

## Directory Layout

```
superset/ai_assistant/
├── __init__.py          Flask blueprint registration  (/api/v1/ai)
├── api.py               REST endpoints (health, config, chat)
├── agent.py             LangGraph ReAct agent + invoke_agent()
├── config.py            LLM factory (Anthropic / OpenAI)
├── conversation.py      In-memory conversation history with TTL cleanup
└── mcp_client.py        Loads 19 MCP tools as LangChain Tool objects
```

---

## API Endpoints

All routes are registered under the `ai_assistant_bp` blueprint at `/api/v1/ai`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/ai/health` | None | Returns LLM provider status |
| `GET` | `/api/v1/ai/config` | None | Returns active provider / model |
| `POST` | `/api/v1/ai/chat` | Session cookie | Main chat endpoint |

### POST `/api/v1/ai/chat`

**Request**

```json
{
  "message": "What charts do I have?",
  "session_id": "optional-string",
  "context": {
    "dashboard_id": 7,
    "chart_id": 42
  }
}
```

**Response (success)**

```json
{
  "success": true,
  "response": "You have 12 charts...",
  "conversation_id": "cc89754a-...",
  "metadata": { "query": "What charts do I have?", "message_count": 5 }
}
```

**Response (error)**

```json
{
  "success": false,
  "response": "I encountered an error...",
  "error": "Agent query failed: ..."
}
```

---

## LLM Configuration (`config.py`)

Provider is selected via environment variable. The factory returns a LangChain
`BaseChatModel`.

```bash
# Anthropic (default in this deployment)
AI_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
AI_LLM_MODEL=claude-sonnet-4-6

# OpenAI
AI_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
AI_LLM_MODEL=gpt-4
```

---

## Agent (`agent.py`)

`create_superset_agent()` builds a LangGraph ReAct agent:

1. Calls `get_mcp_tools()` to load up to 19 LangChain tools from the in-process
   FastMCP instance.
2. Calls `get_llm_instance()` from `config.py`.
3. Constructs the agent with `create_react_agent(llm, tools)` from
   `langgraph.prebuilt`.

`invoke_agent(query, context, conversation_history)`:

1. Prepends the system prompt (tool-first rules, verification checklist).
2. Appends full conversation history for multi-turn context.
3. Calls `agent.invoke({"messages": [...]})`.
4. Extracts the last message from the response.

> **Import note**: use `from langgraph.prebuilt import create_react_agent`.
> `langchain.agents.create_react_agent` does **not** exist in the installed
> version.

---

## Conversation History (`conversation.py`)

- Each chat session is identified by `conversation_id` (UUID).
- History is stored in-memory with automatic TTL expiry (cleaned up on each
  request).
- The client receives `conversation_id` in the first response and must pass it
  back as `session_id` in subsequent requests to maintain context.

---

## MCP Client (`mcp_client.py`)

Tools are loaded **in-process** — no HTTP calls to the MCP service:

```python
from superset.mcp_service.app import mcp   # global FastMCP instance
tools = mcp._tool_manager._tools            # dict of 19 registered tools
```

Each tool is wrapped as a `langchain_core.tools.Tool` with:
- A sync `func` that calls `asyncio.run(tool_callable(request_obj))`.
- A FastMCP `SessionlessContext` (overrides `log()` to use Python logging
  instead of requiring a live MCP WebSocket session).
- A `db.session.merge(user)` call before each tool to avoid SQLAlchemy
  cross-session `InvalidRequestError`.

---

## Running Locally

```bash
# 1. Start all services
docker compose up -d

# 2. Verify health
curl http://localhost:8088/api/v1/ai/health

# 3. Verify tools loaded (should show 19)
docker compose logs superset | grep "Loaded.*MCP tools"

# 4. Send a message
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -b "$(curl -sc /tmp/c http://localhost:8088/login/ > /dev/null && cat /tmp/c)" \
  -d '{"message": "List available datasets"}'
```

---

## Key Known Issues & Fixes

| Error | Root cause | Fix applied |
|-------|-----------|-------------|
| `list_datasets() missing 1 required positional argument: 'request'` | `@parse_request` expects first positional arg | `tool_callable(request_obj)` not `**kwargs` |
| `DetachedInstanceError: user.roles` | SQLAlchemy user object detached across `asyncio.run()` | `try/except DetachedInstanceError` in `auth.py` |
| `InvalidRequestError: Object already attached to session N` | Each `asyncio.run()` creates a new scoped session | `db.session.merge(user)` in `_setup_user_context()` |
| `RuntimeError: No active context found` | `@parse_request` calls `get_context()` which needs FastMCP ContextVar | `SessionlessContext` + `set_context()` in `mcp_client.py` |
| `RuntimeError: session is not available` | `Context.log()` tries to send over MCP WebSocket | `SessionlessContext.log()` routes to Python logger |
| `ValidationError: 'big_number_total' not a valid tag` | LLM passed unsupported `chart_type` | Added `BigNumberChartConfig` to `ChartConfig` union |

> See [`mcp/troubleshooting.md`](../mcp/troubleshooting.md) for full diagnostic
> commands and fix details.
