# Quick Start: MCP Backend for AI Assistant

## 1️⃣ Start Superset with MCP Service

```bash
cd /home/kapa-bi-02/superset

# Stop existing containers
docker compose down

# Start with MCP profile enabled
docker compose up -d --profile mcp

# Wait for services to initialize
sleep 30

# Verify both services are running
docker compose ps
```

You should see:
- `superset` (port 8088)
- `superset-mcp` (port 5008)

## 2️⃣ Verify MCP Service

```bash
# Check MCP service health
curl http://localhost:5008/health

# List all available tools (should show 20+)
curl http://localhost:5008/tools | head -100
```

## 3️⃣ Configure LLM Provider

Set your LLM API key:

```bash
# Option A: OpenAI
docker compose exec superset bash -c "
  export OPENAI_API_KEY='sk-your-key-here'
  export AI_LLM_PROVIDER=openai
  export AI_LLM_MODEL=gpt-4
  echo 'Configured for OpenAI'
"

# Option B: Anthropic
docker compose exec superset bash -c "
  export ANTHROPIC_API_KEY='sk-ant-your-key-here'
  export AI_LLM_PROVIDER=anthropic
  export AI_LLM_MODEL=claude-3-5-sonnet-20241022
  echo 'Configured for Anthropic'
"
```

Or add to `.env` file:

```bash
# .env
OPENAI_API_KEY=sk-...
AI_LLM_PROVIDER=openai
AI_LLM_MODEL=gpt-4
```

Then restart:

```bash
docker compose down
docker compose up -d --profile mcp
```

## 4️⃣ Test the Chat Endpoint

```bash
# Test API endpoint
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What dashboards do I have?",
    "session_id": "test-user"
  }' | jq .
```

Expected response:
```json
{
  "success": true,
  "response": "I found the following dashboards in your Superset instance..."
}
```

## 5️⃣ Try Agent Queries

Test various queries that use different MCP tools:

```bash
# Query 1: List dashboards
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me all dashboards" }' | jq .response

# Query 2: Find charts
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What are my most viewed charts?"}' | jq .response

# Query 3: Get instance info
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me about this Superset instance"}' | jq .response

# Query 4: Find datasets
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What datasets are available?"}' | jq .response
```

## 6️⃣ View Logs

Check what's happening:

```bash
# Tail AI Assistant logs
docker compose logs -f superset | grep -E "(AI|MCP|agent|tool)"

# Check for errors
docker compose logs superset | grep -E "(ERROR|error|Error)"
```

## 7️⃣ Access Chat UI

Open Superset in browser:

```
http://localhost:8088/
```

Login: `admin` / `admin`

If you've integrated the chat widget into the dashboard, you should see the chat button!

Otherwise, you can test via:
- API directly (curl examples above)
- React component integration
- Python SDK

## 🔍 Debugging

### MCP service not responding?

```bash
# Check if service is running
docker compose ps | grep mcp

# View MCP logs
docker compose logs superset-mcp

# Verify port
curl -v http://localhost:5008/health

# Check firewall
sudo netstat -tlnp | grep 5008
```

### Agent not using tools?

```bash
# Check if MCP tools are load
docker compose exec superset python -c "
from superset.ai_assistant.mcp_client import get_mcp_tools
tools = get_mcp_tools()
print(f'Loaded {len(tools)} tools')
"

# View available tools
curl http://localhost:5008/tools | python -m json.tool | head -50
```

### LLM errors?

```bash
# Check if API key is set
docker compose exec superset bash -c "echo \$OPENAI_API_KEY"

# Test LLM directly
docker compose exec superset python -c "
from superset.ai_assistant.config import get_llm_instance
try:
    llm = get_llm_instance()
    print(f'LLM initialized: {llm}')
except Exception as e:
    print(f'Error: {e}')
"
```

## 📋 Checklist

- [ ] Docker Compose running with `--profile mcp`
- [ ] MCP service responds on port 5008
- [ ] LLM API key configured
- [ ] Chat endpoint accessible at `/api/v1/ai/chat`
- [ ] Agent responds to queries
- [ ] Tools are being used (check logs for "Calling MCP tool")

## 🚀 Next Steps

1. **Integrate into Dashboard** (optional)
   ```tsx
   // In DashboardPage.tsx
   import { AIChatPanel } from 'src/components';
   
   <AIChatPanel floatingButton />
   ```

2. **Customize System Prompt** (if needed)
   - Edit `SYSTEM_PROMPT` in agent.py
   - Restart: `docker compose restart superset`

3. **Add Custom Tools** (if needed)
   - Create LangChain tools
   - Pass to `create_superset_agent(tools=[...])`

4. **Monitor Performance**
   - Watch MCP service logs for timing
   - Monitor agent response times
   - Scale MCP service if needed

## 📚 More Info

- Full guide: `/superset/ai_assistant/MCP_INTEGRATION.md`
- Migration summary: `/superset/ai_assistant/MCP_MIGRATION_SUMMARY.md`
- MCP service: `/superset/mcp_service/README.md`

## 💡 Tips

**Faster Testing** - Use Python REPL:

```python
from superset.ai_assistant.agent import invoke_agent

response = invoke_agent("List my dashboards")
print(response["response"])
```

**Check Tool Loading** - View console output:

```bash
docker compose logs superset 2>&1 | grep -E "(✅|🔌|Loading|tool|MCP)"
```

**Monitor Tool Usage** - Watch for calls:

```bash
docker compose logs -f superset | grep "Calling MCP tool"
```

---

**Ready to go!** 🎉 Start with step 1 and you should have a working AI Agent with 20+ MCP tools in minutes.
