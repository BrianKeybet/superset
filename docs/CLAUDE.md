# Superset AI Assistant - Setup Guide

## Overview

The Superset AI Assistant provides a conversational interface for data analysis using LangChain and your choice of LLM provider:
- **OpenAI GPT-4** — Superior chat quality and reasoning
- **Anthropic Claude** — Best for complex analysis and long contexts

The assistant automatically integrates with Superset's native MCP tools to generate charts, dashboards, and SQL queries through natural language.

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Install AI Assistant dependencies
pip install -r requirements/ai-assistant.txt
```

### 2. Configure Environment Variables

Edit `docker/.env-local` and uncomment your preferred LLM provider:

#### Option A: OpenAI GPT-4 (Recommended)
```bash
AI_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...your-openai-api-key...
OPENAI_MODEL=gpt-4
```

#### Option B: Anthropic Claude
```bash
AI_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...your-anthropic-api-key...
ANTHROPIC_MODEL=claude-sonnet-5
```

### 3. Optional: Customize AI Settings

```bash
# Temperature: 0-1 (higher = more creative, lower = more focused)
AI_TEMPERATURE=0.7

# Max tokens per response
AI_MAX_TOKENS=4096

# Enable streaming responses
AI_ENABLE_STREAMING=true
```

### 4. Restart Superset

```bash
docker-compose down
docker-compose up -d
```

### 5. Test the Setup

```bash
# Check health status
curl http://localhost:8088/api/v1/ai/health

# Get current configuration
curl http://localhost:8088/api/v1/ai/config
```

---

## 📝 API Endpoints

### Chat Endpoint

**POST** `/api/v1/ai/chat`

Send a natural language question to the AI assistant.

**Request:**
```json
{
  "message": "What are our top 10 sales by region?"
}
```

**Response:**
```json
{
  "success": true,
  "response": "I'll query the sales data and create a visualization...",
  "metadata": {
    "query": "What are our top 10 sales by region?"
  }
}
```

### Configuration Endpoint

**GET** `/api/v1/ai/config`

Get current AI configuration and LLM provider status.

**Response:**
```json
{
  "success": true,
  "config": {
    "provider": "openai",
    "openai_api_key": true,
    "openai_model": "gpt-4",
    "temperature": 0.7,
    "max_tokens": 4096,
    "streaming_enabled": true
  },
  "message": "Using openai as LLM provider"
}
```

### Health Endpoint

**GET** `/api/v1/ai/health`

Check AI assistant health and LLM provider availability.

**Response:**
```json
{
  "success": true,
  "status": "ok",
  "llm_status": "ok",
  "llm_message": "LLM ready: gpt-4"
}
```

---

## 🔑 API Key Setup

### OpenAI

1. Go to [OpenAI Platform](https://platform.openai.com)
2. Create an API key in Settings → API Keys
3. Set `OPENAI_API_KEY` in `docker/.env-local`
4. Usage typically costs $0.01-0.03 per conversational turn

### Anthropic

1. Go to [Anthropic Console](https://console.anthropic.com)
2. Create an API key in Settings
3. Set `ANTHROPIC_API_KEY` in `docker/.env-local`
4. Usage typically costs $0.003-0.015 per conversational turn

---

## 🛠️ Architecture

```
┌─ Browser UI (Superset)
│  └─ React Chat Component (to be added in frontend)
│
├─ Backend: `/api/v1/ai/chat`
│  ├─ Flask Blueprint: `superset/ai_assistant/`
│  │  ├─ api.py        — REST endpoints
│  │  ├─ agent.py      — LangChain agent
│  │  └─ config.py     — LLM provider setup
│  │
│  └─ LangChain Agent
│     ├─ ChatOpenAI (if provider=openai)
│     └─ ChatAnthropic (if provider=anthropic)
│
└─ MCP Tools Integration (Future)
   ├─ list_dashboards()
   ├─ list_charts()
   ├─ execute_sql()
   ├─ create_chart()
   └─ ... (more tools)
```

---

## 🧪 Testing Locally

### Test with curl

```bash
# Test chat endpoint
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "List all available dashboards"}'

# Check configuration
curl http://localhost:8088/api/v1/ai/config

# Health check
curl http://localhost:8088/api/v1/ai/health
```

### Test with Python (Client)

```python
import requests
import json

BASE_URL = "http://localhost:8088/api/v1/ai"

# Send a chat message
response = requests.post(
    f"{BASE_URL}/chat",
    json={"message": "What are our top performing dashboards?"}
)
print(json.dumps(response.json(), indent=2))

# Check config
config = requests.get(f"{BASE_URL}/config").json()
print(f"Using LLM: {config['config']['provider']}")
```

---

## ⚙️ Switching LLM Providers

To switch providers without downtime:

1. Edit `docker/.env-local`
2. Change `AI_LLM_PROVIDER` to `openai` or `anthropic`
3. Set the corresponding API key
4. Restart Superset:
   ```bash
   docker-compose restart superset
   ```

The next API call will use the new provider.

---

## 📚 Next Steps

### Phase 2: Frontend Integration
Create a React chat component in `superset-frontend/src/components/AIChatWidget/` that:
- Renders in dashboard sidebar
- Sends messages to `/api/v1/ai/chat`
- Displays AI responses
- Renders generated charts/dashboards

### Phase 3: MCP Tool Integration
Connect LangChain agent to Superset's MCP tools:
- Query dashboards and charts
- Execute dynamic SQL queries
- Create visualizations automatically
- Suggest chart types based on data

### Phase 4: Session Management
Add persistent chat history:
- Store conversations in database
- Session-based context
- User-specific chat threads

---

## 🐛 Troubleshooting

### "OPENAI_API_KEY is required"
**Solution:** Set `OPENAI_API_KEY` in `docker/.env-local` or environment

### "Invalid AI_LLM_PROVIDER"
**Solution:** Use only `openai` or `anthropic`

### "LLM endpoint timeout"
**Solution:** Check network connectivity and API key validity

### "Chat returns empty response"
**Solution:** Check logs: `docker-compose logs superset | grep "Agent query"`

---

## 🔒 Security Considerations

⚠️ **Important:**
- **Never commit API keys** to version control
- Use `.env-local` (which is gitignored) for sensitive keys
- Rotate API keys regularly
- Implement rate limiting before production (see TODO in `api.py`)
- Add authentication checks (commented in `api.py`)

---

## 📖 Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_LLM_PROVIDER` | `openai` | LLM provider: `openai` or `anthropic` |
| `OPENAI_API_KEY` | *(empty)* | OpenAI API key (required if provider=openai) |
| `OPENAI_MODEL` | `gpt-4` | OpenAI model name |
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key (required if provider=anthropic) |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Anthropic model name |
| `AI_TEMPERATURE` | `0.7` | LLM temperature (0-1) |
| `AI_MAX_TOKENS` | `4096` | Max tokens per response |
| `AI_ENABLE_STREAMING` | `true` | Enable streaming responses |

---

## 📞 Support

For issues or questions:
1. Check logs: `docker-compose logs -f superset`
2. Verify API keys are set: `docker-compose exec superset env | grep -i "API_KEY\|LLM"`
3. Test endpoints with curl (see Testing section)
