# AI Assistant — Documentation Hub

This is the single entry point for all documentation covering the Superset AI
Assistant: the React chat widget, the Flask/LangGraph backend, and the MCP tool
integration layer.

---

## Structure

```
docs/ai-assistant/
├── README.md                  ← you are here
├── backend/
│   └── overview.md            Backend API, agent, LLM config, endpoints
├── frontend/
│   └── overview.md            React widget, props, integration patterns
└── mcp/
    ├── integration.md         How the agent loads and calls MCP tools
    ├── architecture.md        Service design, deployment, scaling
    ├── security.md            Auth, JWT, RBAC, RLS
    └── troubleshooting.md     Known issues, fixes, diagnostic commands
```

---

## Quick Start (60 seconds)

### 1. Start services

```bash
docker compose up -d
```

### 2. Verify backend

```bash
curl http://localhost:8088/api/v1/ai/health
```

### 3. Verify MCP tools (19 expected)

```bash
docker compose logs superset | grep "Loaded.*MCP tools"
```

### 4. Send a test message

```bash
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -b "session=..." \
  -d '{"message": "List my datasets"}'
```

### 5. Use the React widget

```tsx
import { AIChatPanel } from 'src/components';
// Add to any page:
<AIChatPanel floatingButton drawerWidth={420} />
```

---

## What Was Built

| Layer | What | Location |
|-------|------|----------|
| Frontend | React chat widget (floating button + drawer) | `superset-frontend/src/components/AIChatWidget/` |
| Backend API | Flask blueprint with `/api/v1/ai/*` endpoints | `superset/ai_assistant/` |
| Agent | LangGraph ReAct agent with 19 MCP tools | `superset/ai_assistant/agent.py` |
| MCP Tools | 19 tools (charts, dashboards, datasets, SQL, system) | `superset/mcp_service/` |
| Auth bridge | `mcp_auth_hook` — sets Flask `g.user` per tool call | `superset/mcp_service/auth.py` |

---

## Environment Variables

```bash
# LLM provider (required)
AI_LLM_PROVIDER=anthropic          # or: openai
ANTHROPIC_API_KEY=sk-ant-...       # or: OPENAI_API_KEY=sk-...
AI_LLM_MODEL=claude-sonnet-4-6     # or: gpt-4

# MCP service location (defaults work for Docker)
MCP_SERVICE_HOST=superset-mcp
MCP_SERVICE_PORT=5008

# Dev auth (MCP tools run as this user)
MCP_DEV_USERNAME=admin
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/ai/health` | LLM and MCP status |
| `GET` | `/api/v1/ai/config` | Provider info |
| `POST` | `/api/v1/ai/chat` | Send a message, get a response |

**Chat request/response:**

```json
// POST /api/v1/ai/chat
{ "message": "What charts do I have?", "session_id": "abc123" }

// Response
{ "success": true, "response": "...", "conversation_id": "abc123" }
```

---

## Available MCP Tools (19)

| Domain | Tools |
|--------|-------|
| Charts | `generate_chart`, `get_chart_data`, `get_chart_info`, `get_chart_preview`, `list_charts`, `update_chart`, `update_chart_preview` |
| Dashboards | `add_chart_to_existing_dashboard`, `generate_dashboard`, `get_dashboard_info`, `list_dashboards` |
| Datasets | `get_dataset_info`, `list_datasets` |
| SQL Lab | `execute_sql`, `open_sql_lab_with_context` |
| Explore | `generate_explore_link` |
| System | `get_instance_info`, `get_schema`, `health_check` |

---

## Original Source Documents

> These files remain in place. The consolidated docs above summarise them.
> Where detail is needed, follow these links.

### Frontend
| File | Purpose |
|------|---------|
| [`superset-frontend/src/components/AIChatWidget/AIchatReadME.md`](../../superset-frontend/src/components/AIChatWidget/AIchatReadME.md) | Widget features and props |
| [`superset-frontend/src/components/AIChatWidget/INTEGRATION_GUIDE.md`](../../superset-frontend/src/components/AIChatWidget/INTEGRATION_GUIDE.md) | 6 integration patterns with code examples |
| [`superset-frontend/src/components/AIChatWidget/MODULE.md`](../../superset-frontend/src/components/AIChatWidget/MODULE.md) | Component architecture |

### Backend
| File | Purpose |
|------|---------|
| [`superset/ai_assistant/README_MCP.md`](../../superset/ai_assistant/README_MCP.md) | Agent + MCP client usage |
| [`superset/ai_assistant/MCP_QUICKSTART.md`](../../superset/ai_assistant/MCP_QUICKSTART.md) | Step-by-step start guide |

### MCP Service
| File | Purpose |
|------|---------|
| [`superset/mcp_service/README.md`](../../superset/mcp_service/README.md) | Full MCP service reference |
| [`superset/mcp_service/ARCHITECTURE.md`](../../superset/mcp_service/ARCHITECTURE.md) | Flask singleton, multitenancy, connection pooling, k8s |
| [`superset/mcp_service/SECURITY.md`](../../superset/mcp_service/SECURITY.md) | JWT, RBAC, RLS, audit |
| [`superset/mcp_service/PRODUCTION.md`](../../superset/mcp_service/PRODUCTION.md) | Production deployment runbook |
| [`superset/mcp_service/docs/tool-search-optimization.md`](../../superset/mcp_service/docs/tool-search-optimization.md) | Tool description optimisation for LLM |

### Root-level delivery summaries
| File | Purpose | Status |
|------|---------|--------|
| [`AI_ASSISTANT_DELIVERY.md`](../../AI_ASSISTANT_DELIVERY.md) | Full delivery checklist | **Authoritative** |
| [`REACT_CHAT_WIDGET_SUMMARY.md`](../../REACT_CHAT_WIDGET_SUMMARY.md) | Frontend delivery detail | **Authoritative** |
| [`IMPLEMENTATION_SUMMARY.md`](../../IMPLEMENTATION_SUMMARY.md) | Project overview | **Authoritative** |
| [`MCP_FIX_SUMMARY_FINAL.md`](../../MCP_FIX_SUMMARY_FINAL.md) | In-process tool discovery fix | **Authoritative** |
| [`MCP_TOOL_FIX_QUICKREF.md`](../../MCP_TOOL_FIX_QUICKREF.md) | Diagnostic command reference | **Authoritative** |
| [`MCP_MAINTENANCE_GUIDE.md`](../../MCP_MAINTENANCE_GUIDE.md) | Ops maintenance guide | **Authoritative** |

---

## Superseded / Redundant Files

These files contain content that has been consolidated above. They are kept for
historical reference but should **not** be used as the source of truth.

| File | Superseded by |
|------|--------------|
| `MCP_FIX_EXPLANATION.md` | `mcp/troubleshooting.md` + `MCP_FIX_SUMMARY_FINAL.md` |
| `MCP_FIX_SUMMARY.md` | `MCP_FIX_SUMMARY_FINAL.md` |
| `MCP_TOOL_ANALYSIS_COMPLETE.md` | `mcp/troubleshooting.md` |
| `MCP_TOOL_FAILURE_ANALYSIS.md` | `mcp/troubleshooting.md` |
| `MCP_TOOL_FIX_IMPLEMENTATION.md` | `mcp/integration.md` + `mcp/troubleshooting.md` |
| `MCP_TOOL_FIX_SUMMARY.md` | `MCP_FIX_SUMMARY_FINAL.md` |
| `superset/ai_assistant/FINAL_CHECKLIST.md` | `AI_ASSISTANT_DELIVERY.md` |
| `superset/ai_assistant/IMPLEMENTATION_COMPLETE.md` | `AI_ASSISTANT_DELIVERY.md` |
| `superset/ai_assistant/MCP_MIGRATION_SUMMARY.md` | `mcp/integration.md` |
| `superset/ai_assistant/MCP_INTEGRATION.md` | `mcp/integration.md` |
