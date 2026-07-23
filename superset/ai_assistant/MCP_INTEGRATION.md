#  AI Assistant with Superset's Native MCP Service

This guide explains how the AI Assistant now uses Superset's native **Model Context Protocol (MCP)** service as its backend for tool capabilities.

## 🎯 Overview

The AI Assistant has been refactored to use Superset's native MCP service instead of custom tool implementations. This provides several advantages:

### Benefits of MCP Integration

| Aspect | Before (Custom Tools) | After (MCP) |
|--------|----------------------|------------|
| **Tool Discovery** | Hard-coded in Python | Dynamic from MCP service |
| **Tool Quality** | Custom implementations, edge cases | Battle-tested Superset tools |
| **Circular Imports** | ✅ Fixed with lazy loading | ✅ Eliminated entirely |
| **Database Queries** | Limited read-only access | Full MCP tool access |
| **Maintenance** | Update agent.py for each change | MCP service updates apply automatically |
| **Tool Availability** | 4 tools (custom) | 20+ tools (MCP service) |
| **Schema Discovery** | Manual querying | Automatic via get_schema tool |
| **Chart & Dashboard Creation** | No | Yes (generate_chart, generate_dashboard) |
| **SQL Lab Integration** | Partial | Full (execute_sql tool) |

## 📋 Architecture

```
User Query (Chat Input)
       ↓
   LangChain Agent
       ↓
   LLM (OpenAI/Anthropic)
       ↓
   Agent Selects Tools
       ↓
   MCP Client (mcp_client.py)
       ↓
   HTTP Requests to MCP Service (port 5008)
       ↓
   Superset MCP Service
       ↓
   Superset APIs / Database
       ↓
   Tool Results → Agent → Final Response → User
```

## 🚀 Setup & Configuration

### Prerequisites

1. **Superset Running with MCP Service**
   
   The MCP service must be enabled in your Docker Compose setup:
   
   ```bash
   # Start Superset with MCP profile enabled
   docker compose up -d --profile mcp superset
   ```
   
   This starts the MCP service on port 5008 alongside Superset (port 8088).

2. **Environment Variables Set**
   
   The AI Assistant requires LLM configuration:
   
   ```bash
   # OpenAI Configuration
   OPENAI_API_KEY=sk-...
   AI_LLM_PROVIDER=openai
   AI_LLM_MODEL=gpt-4
   
   # OR Anthropic Configuration
   ANTHROPIC_API_KEY=sk-ant-...
   AI_LLM_PROVIDER=anthropic
   AI_LLM_MODEL=claude-3-5-sonnet-20241022
   ```

### Verification

Check that both services are running:

```bash
# Check Superset
curl http://localhost:8088/health

# Check MCP Service
curl http://localhost:5008/health

# View MCP Tools (should return JSON array of tool definitions)
curl http://localhost:5008/tools
```

## 🛠️ Available MCP Tools

The MCP service provides 20+ tools across 6 categories:

### Dashboard Management
- `list_dashboards` - Find dashboards with filters
- `get_dashboard_info` - Get dashboard details and charts
- `generate_dashboard` - Create a dashboard from chart IDs
- `add_chart_to_existing_dashboard` - Add a chart to a dashboard

### Chart Operations
- `list_charts` - Search and filter charts
- `get_chart_info` - Get chart metadata and configuration
- `get_chart_preview` - Get a visual preview (image URL)
- `get_chart_data` - Extract underlying chart data
- `generate_chart` - Create and save a new chart
- `generate_explore_link` - Create an interactive explore URL
- `update_chart` - Modify existing chart configuration
- `update_chart_preview` - Update cached preview

### Dataset & Schema Discovery
- `list_datasets` - Find datasets with filters
- `get_dataset_info` - Get dataset schema and metadata
- `get_schema` - Get schema for charts/datasets/dashboards

### SQL Lab Integration
- `execute_sql` - Run SQL queries on configured databases
- `open_sql_lab_with_context` - Generate SQL Lab URL with pre-filled query

### System Information
- `get_instance_info` - Get instance statistics and current user
- `health_check` - Check MCP service health

### Example Queries

The agent can now answer questions like:

```
User: "What is the most viewed chart?"
→ Agent uses: list_charts(sort="view_count") → get_chart_preview()

User: "Create a bar chart showing sales by region"
→ Agent uses: list_datasets() → get_dataset_info() → generate_chart()

User: "Add my top 3 charts to a new dashboard"
→ Agent uses: list_charts(sort="view_count", limit=3) → generate_dashboard()

User: "What columns are available in the sales dataset?"
→ Agent uses: list_datasets(name="sales") → get_dataset_info()

User: "Execute: SELECT COUNT(*) FROM my_table"
→ Agent uses: execute_sql(database_id=1, sql="SELECT COUNT(*) FROM my_table")
```

## 📝 Code Structure

### Files

| File | Purpose |
|------|---------|
| `mcp_client.py` | HTTP-based MCP client for tool discovery and invocation |
| `agent.py` | LangChain agent that uses MCP tools |
| `config.py` | LLM provider configuration (OpenAI/Anthropic) |
| `api.py` | Flask REST endpoints for the chat interface |
| `__init__.py` | Blueprint registration and CSRF setup |

### Key Functions

#### `mcp_client.py`

```python
# Main client for connecting to MCP service
class SuprsetMCPClient:
    def __init__(host="localhost", port=5008, timeout=30)
    def call_tool(tool_name: str, tool_input: dict) → dict
    def list_tools() → list[dict]
    def get_tool_definition(tool_name: str) → dict

# Convert MCP tool to LangChain tool
def create_mcp_langchain_tool(mcp_client, tool_name, definition) → Tool

# Get all MCP tools
def get_mcp_tools(host="localhost", port=5008, tool_filter=None) → list[Tool]
```

#### `agent.py`

```python
# Create an agent with MCP tools
def create_superset_agent(tools: list[Tool] = None) → Agent

# Invoke the agent with a user query
def invoke_agent(query: str, tools: list[Tool] = None) → dict
    {
        "success": bool,
        "response": str,       # LLM response
        "error": Optional[str], # Error message if any
        "metadata": {
            "query": str,
            "message_count": int
        }
    }
```

## 🔌 Usage Examples

### Python API

```python
from superset.ai_assistant.agent import invoke_agent

# Simple query
response = invoke_agent("What is my most viewed chart?")
print(response["response"])

# With custom tools (if needed)
from superset.ai_assistant.mcp_client import get_mcp_tools

tools = get_mcp_tools(tool_filter=["list_charts", "get_chart_info"])
response = invoke_agent("List all charts", tools=tools)
```

### REST API

```bash
# Chat endpoint
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Create a bar chart showing revenue by region",
    "session_id": "user-123"
  }'

# Response
{
  "success": true,
  "response": "I'll create a bar chart for you...",
  "session_id": "user-123"
}
```

### React Component

```tsx
import { AIChatPanel } from 'src/components';

export function MyDashboard() {
  return (
    <>
      <DashboardContent />
      <AIChatPanel floatingButton />
    </>
  );
}
```

## 🐛 Troubleshooting

### Issue: "MCP service not accessible"

**Cause:** MCP service not running or port 5008 blocked

**Solution:**
```bash
# Check if MCP service is running
docker ps | grep mcp

# Start with MCP profile
docker compose up -d --profile mcp

# Verify connectivity
curl http://localhost:5008/health
```

### Issue: "No MCP tools available"

**Cause:** MCP service running but unable to list tools

**Solution:**
```bash
# Check MCP service logs
docker compose logs superset-mcp

# Verify MCP port is 5008
docker compose ps | grep mcp

# Alternative: Check if Superset needs reinitialization
docker compose exec superset superset init
```

### Issue: "Tool execution failed: Connection refused"

**Cause:** MCP service not accessible from frontend/backend

**Solution:**
```bash
# Verify port mapping
docker compose config | grep 5008

# Check within container
docker compose exec superset curl http://localhost:5008/health

# Restart services
docker compose down
docker compose up -d --profile mcp
```

### Issue: LLM provider error

**Cause:** API keys not configured

**Solution:**
```bash
# Check environment variables
docker compose exec superset echo $OPENAI_API_KEY

# Set API keys
export OPENAI_API_KEY=sk-...
docker compose up -d

# OR add to .env file
echo "OPENAI_API_KEY=sk-..." >> .env
docker compose up -d
```

## ✅ For Production

1. **Enable MCP Service with feature flag**
   ```python
   # In superset_config.py
   FEATURE_FLAGS = {
       "MCP_SERVICE_ENABLED": True,
   }
   ```

2. **Configure MCP Authentication** (if required)
   ```python
   MCP_SERVICE_AUTH_TOKEN = "your-token-here"
   ```

3. **Set appropriate timeouts**
   ```python
   AI_MCP_TIMEOUT = 30  # seconds
   ```

4. **Monitor MCP service health**
   ```bash
   # Add health check to monitoring
   curl http://localhost:5008/health
   ```

## 🔮 Future Enhancements

- [ ] Custom tools for domain-specific operations
- [ ] Tool caching for improved performance
- [ ] MCP service redundancy/failover
- [ ] Advanced error recovery strategies
- [ ] Tool execution rate limiting
- [ ] Audit logging for tool usage

## 📚 References

- [Superset MCP Service Documentation](../mcp_service/README.md)
- [MCP Specification](https://modelcontextprotocol.io/)
- [LangChain Tools Documentation](https://python.langchain.com/docs/modules/tools/)
- [Apache Superset Documentation](https://superset.apache.org/)
