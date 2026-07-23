# Apache Superset AI Agent - MCP Tool Discovery Failure Analysis

**Date**: April 29, 2026  
**Issue**: Agent initialization completes but without any MCP tools (0 tools loaded)  
**Status**: Root cause identified with recommended fixes

---

## Executive Summary

The Superset AI Agent fails to discover or load any MCP tools due to a **URL construction bug** combined with **missing MCP service**. The agent gracefully degrades to operating without tools, completing queries without access to Superset's capabilities.

### Key Failure Points:
1. **URL Path Bug**: `urljoin()` incorrectly strips `/mcp/` prefix
2. **Missing MCP Service**: The Superset MCP service is not running or not properly exposed
3. **Silent Degradation**: Agent continues without tools instead of failing loudly
4. **Configuration Mismatch**: Environment hostname (`superset-mcp`) differs from logs (`localhost`)

---

## End-to-End Flow & Failure Analysis

### Stage 1: API Endpoint Invoked ✅
**File**: [superset/ai_assistant/api.py](superset/ai_assistant/api.py#L35)  
**Endpoint**: `POST /api/v1/ai/chat`

```
Log: 2026-04-29 08:44:25 "POST /api/v1/ai/chat HTTP/1.1" 200
```

**What happens**:
- Client sends: `{"message": "How many datasets do I have?"}`
- API handler `chat()` receives request
- Extracts message, conversation ID, and optional context

**Status**: ✅ Working correctly

---

### Stage 2: Agent Invocation ✅
**File**: [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py#L203)  
**Function**: `invoke_agent(query, tools=None, context, conversation_history)`

```python
# Line 203-225
agent = create_superset_agent(tools)  # tools=None, so triggers MCP discovery
```

**What should happen**:
1. Create agent with LLM instance
2. Discover MCP tools (since `tools=None`)
3. Setup agent with discovered tools

**Status**: ✅ Initiated correctly

---

### Stage 3: LLM Instance Creation ✅
**File**: [superset/ai_assistant/config.py](superset/ai_assistant/config.py#L48)  
**Function**: `get_llm_instance()`

```
Log: 2026-04-29 08:44:12,533:INFO:superset.ai_assistant.config:🤖 Initializing Anthropic LLM: claude-sonnet-4-6
```

**What happens**:
- Reads `ANTHROPIC_API_KEY` from environment
- Creates `ChatAnthropic` instance with `claude-sonnet-4-6` model
- Returns configured LLM ready for agent use

**Status**: ✅ LLM initialized successfully

---

### Stage 4: MCP Tools Discovery 🔴 **FAILURE STARTS HERE**
**File**: [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py#L147)  
**Function**: `create_superset_agent(tools=None)`

```
Log: 2026-04-29 08:44:12,577:INFO:superset.ai_assistant.agent:🔌 Connecting to Superset MCP service on localhost:5008 to discover available tools...
```

**What the log says**:
- Trying to connect to `localhost:5008`

**What actually happens** (see Stage 4a):
- `get_mcp_tools()` is called with default host/port
- `DEFAULT_MCP_HOST = os.getenv("MCP_SERVICE_HOST", "localhost")`
- If `MCP_SERVICE_HOST` environment variable is set to `superset-mcp`, it uses that instead
- Actual URL attempted: `http://superset-mcp:5008/mcp/tools` (no trailing slash causes issue)

**Status**: ⚠️ Log is misleading; actual connection uses `superset-mcp` hostname

---

### Stage 4a: MCP Client Initialization 🔴 **BUG #1: URL CONSTRUCTION**
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L76)  
**Class**: `SupersetMCPClient.__init__()`

```python
# Line 85
self.base_url = f"http://{host}:{port}/mcp"  # ❌ NO TRAILING SLASH
```

**The Bug**:
```python
from urllib.parse import urljoin

base_url = "http://superset-mcp:5008/mcp"  # Missing trailing slash
url = urljoin(base_url, "tools")
# Result: "http://superset-mcp:5008/tools"  ❌ WRONG!
# Expected: "http://superset-mcp:5008/mcp/tools" ✅ CORRECT

# Why? urljoin treats last segment as replaceable without trailing slash:
# urljoin("http://example.com/mcp", "tools") → replaces "mcp" with "tools"
# urljoin("http://example.com/mcp/", "tools") → appends "tools" to "mcp/"
```

**Impact**: All URL construction using `urljoin()` fails:
- Line 136: `url = urljoin(self.base_url, f"tools/{tool_name}")` → `/tools/...` ❌
- Line 191: `url = urljoin(self.base_url, "rpc")` → `/rpc` ❌
- Line 233: `url = urljoin(self.base_url, "tools")` → `/tools` ❌

**Status**: 🔴 **Critical bug in URL construction**

---

### Stage 4b: Initial Service Health Check ⚠️ **BUG #2: INCOMPLETE HEALTH CHECK**
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L96)  
**Method**: `SupersetMCPClient._is_service_available()`

```python
# Line 100-104
response = requests.get(
    f"http://{self.host}:{self.port}/health",
    timeout=self.timeout
)
```

**What happens**:
- Tries to GET `http://superset-mcp:5008/health`
- If MCP service doesn't exist or `/health` endpoint doesn't exist → returns False
- Logger warns: "MCP service not accessible"
- But continues anyway without throwing exception

**Status**: ⚠️ Health check may pass/fail silently; doesn't prevent list_tools() call

---

### Stage 4c: List MCP Tools 🔴 **FAILURE POINT**
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L227)  
**Method**: `list_tools()`

```
Log: 2026-04-29 08:44:12,622:ERROR:superset.ai_assistant.mcp_client:Failed to list MCP tools: 404 Client Error: Not Found for url: http://superset-mcp:5008/tools
```

**Execution trace**:
```python
# Line 233
url = urljoin(self.base_url, "tools")
# Constructs: "http://superset-mcp:5008/tools" ❌ (due to missing trailing slash)

# Line 235
response = requests.get(url, timeout=self.timeout)

# MCP service at http://superset-mcp:5008 doesn't have:
# - A "/" endpoint mapping to /tools
# - Or the service isn't running at all
# - Or the service is at a different hostname/port

response.raise_for_status()  # Raises HTTPError: 404 Not Found
```

**HTTP Error Details**:
```
requests.exceptions.HTTPError: 404 Client Error: Not Found for url: http://superset-mcp:5008/tools

Traceback:
  File "mcp_client.py", line 235, in list_tools
    response.raise_for_status()
  File ".../requests/models.py", line 1026, in raise_for_status
    raise HTTPError(http_error_msg, response=self)
```

**Status**: 🔴 **404 Error - Endpoint not found**

---

### Stage 4d: Error Handling & Tool List Fallback ⚠️ **SILENT DEGRADATION**
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L391)  
**Function**: `get_mcp_tools()`

```python
# Line 391-410
try:
    mcp_client = SupersetMCPClient(host=host, port=port)
    
    if not mcp_client._is_service_available():
        logger.warning(f"MCP service not available at {mcp_client.base_url}...")
        return []  # ⚠️ Returns empty list silently
    
    tool_definitions = mcp_client.list_tools()  # 🔴 Raises MCPClientError
    # ... never reaches here ...
    
except Exception as e:
    logger.error(f"Failed to get MCP tools: {e}", exc_info=True)
    return []  # ⚠️ Returns empty list, suppressing error

logger.info(f"✅ Loaded {len(langchain_tools)} MCP tools")  # 0 tools!
return []
```

**Logs**:
```
2026-04-29 08:44:12,630:ERROR:superset.ai_assistant.mcp_client:Failed to get MCP tools: Failed to list tools: 404 Client Error: Not Found for url: http://superset-mcp:5008/tools
```

**Status**: ⚠️ **Silent error suppression** - error logged but not propagated

---

### Stage 4e: Agent Creation Without Tools ⚠️ **GRACEFUL DEGRADATION**
**File**: [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py#L147)  
**Function**: `create_superset_agent(tools=None)`

```
Log: 2026-04-29 08:44:12,622:WARNING:superset.ai_assistant.agent:⚠️  No MCP tools available. Using agent without tools. Ensure Superset MCP service is running: docker compose up -d (requires --profile mcp)
Log: 2026-04-29 08:44:12,661:INFO:superset.ai_assistant.agent:✅ Superset AI Agent created with 0 MCP tools:
```

**What happens**:
```python
# Line 147-150
tools = get_mcp_tools()  # Returns [] (empty list)

if not tools:
    logger.warning("⚠️  No MCP tools available...")  # Logs warning
    tools = []  # Explicitly set to empty

# Line 160-164
agent = create_react_agent(llm, tools or [])  # Creates agent with NO TOOLS

logger.info(f"✅ Superset AI Agent created with {len(tools or [])} MCP tools: ")  # 0 tools
```

**Status**: ⚠️ **Agent successfully created with 0 tools** - will run but can't use tools

---

### Stage 5: Agent Execution Without Tools 🔴 **CONSEQUENCE**
**File**: [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py#L225)  
**Function**: Execution continues to `agent.invoke(messages)`

```
Log: 2026-04-29 08:44:12,661:INFO:superset.ai_assistant.agent:Invoking agent with 3 messages (conversation: 1ab18642-8045-43fb-93fa-3015cd0df893)

Log: 2026-04-29 08:44:25,538:INFO:httpx:HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"

Log: 2026-04-29 08:44:25,691:INFO:superset.ai_assistant.agent:✅ Agent query completed: How many datasets do I have?...
```

**What happens**:
1. Agent receives message: "How many datasets do I have?"
2. No MCP tools available to solve this
3. LLM processes message with system prompt instructing tool use
4. LLM responds with its default knowledge (not from Superset data)
5. Response returned to user WITHOUT accessing actual Superset data

**Status**: ⚠️ **Query completes successfully, but without tool-based answers**

---

## Root Causes Summary

| # | Issue | Location | Severity | Category |
|---|-------|----------|----------|----------|
| 1 | **URL Path Bug**: `urljoin()` without trailing slash strips path | [mcp_client.py:85](superset/ai_assistant/mcp_client.py#L85) | 🔴 **Critical** | Code Bug |
| 2 | **Missing/Down MCP Service**: Service not running or wrong hostname | Docker Compose config | 🔴 **Critical** | Deployment/Config |
| 3 | **Misleading Logs**: Says "localhost" but actually uses `superset-mcp` | [agent.py:143](superset/ai_assistant/agent.py#L143) | 🟡 **Medium** | Observability |
| 4 | **Silent Error Suppression**: Exception caught and converted to empty list | [mcp_client.py:407](superset/ai_assistant/mcp_client.py#L407) | 🟡 **Medium** | Error Handling |
| 5 | **No Tool Loading Verification**: Agent doesn't fail if tools unavailable | [agent.py:150-154](superset/ai_assistant/agent.py#L150-L154) | 🟡 **Medium** | Robustness |

---

## Recommended Fixes

### Fix #1: Correct URL Construction (CRITICAL)
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L85)

**Current (Buggy)**:
```python
self.base_url = f"http://{host}:{port}/mcp"
```

**Fix Option A - Add Trailing Slash** (Recommended):
```python
self.base_url = f"http://{host}:{port}/mcp/"
```

**Fix Option B - Use f-strings instead of urljoin**:
```python
# Don't use urljoin(), construct URLs directly
def list_tools(self) -> list[dict[str, Any]]:
    try:
        url = f"{self.base_url}/tools"  # Direct construction
        response = requests.get(url, timeout=self.timeout)
        ...
```

**Fix Option C - Use urljoin with trailing slash consistently**:
```python
self.base_url = f"http://{host}:{port}/mcp/"

def list_tools(self) -> list[dict[str, Any]]:
    url = urljoin(self.base_url, "tools")  # Now works correctly
    # urljoin("http://superset-mcp:5008/mcp/", "tools") 
    # → "http://superset-mcp:5008/mcp/tools" ✅
```

**Recommendation**: Option C is most robust (fixes root cause of urljoin misuse)

---

### Fix #2: Ensure MCP Service is Running & Accessible
**Location**: Docker Compose configuration

**Check 1 - Verify MCP service is in docker-compose**:
```bash
cd /home/kapa-bi-02/superset
grep -A 10 "superset-mcp:" docker-compose.yml | head -20
```

**Check 2 - Start services**:
```bash
# superset-mcp is a built-in service (no profile needed)
# It's defined in docker-compose.yml and always included
docker compose up -d
```

**Check 3 - Verify hostname resolution in container**:
```bash
# Inside Superset container
docker exec superset_app ping superset-mcp  # Should resolve if MCP is running
docker exec superset_app curl http://superset-mcp:5008/health  # Should return 200 if MCP is running
```

**Check 4 - Verify MCP service port exposure**:
```bash
docker ps | grep mcp  # Check if MCP container exists
curl http://localhost:5008/health  # Test from host machine
```

---

### Fix #3: Improve Diagnostics & Logging
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L76)

**Current**:
```python
def __init__(self, host: str = DEFAULT_MCP_HOST, port: int = DEFAULT_MCP_PORT, timeout: int = DEFAULT_MCP_TIMEOUT):
    self.host = host
    self.port = port
    self.timeout = timeout
    self.base_url = f"http://{host}:{port}/mcp"
    
    if not self._is_service_available():
        logger.warning(f"⚠️  MCP service not accessible at {self.base_url}...")
```

**Improved**:
```python
def __init__(self, host: str = DEFAULT_MCP_HOST, port: int = DEFAULT_MCP_PORT, timeout: int = DEFAULT_MCP_TIMEOUT):
    self.host = host
    self.port = port
    self.timeout = timeout
    self.base_url = f"http://{host}:{port}/mcp/"  # ✅ Add trailing slash
    
    logger.debug(f"🔌 MCP Client initialized: base_url={self.base_url}, host={host}, port={port}")
    
    if not self._is_service_available():
        logger.error(  # Changed from warning to error
            f"❌ MCP service not accessible at {self.base_url}. "
            f"Verify:\n"
            f"  1. MCP service container is running: docker ps | grep mcp\n"
            f"  2. Port {port} is exposed: docker port <mcp-container>\n"
            f"  3. Hostname '{host}' resolves correctly\n"
            f"  4. Service is accessible: curl http://{host}:{port}/health\n"
            f"  5. Using docker compose? Start with: docker compose --profile mcp up -d"
        )
```

**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L230)

**Current**:
```python
def list_tools(self) -> list[dict[str, Any]]:
    try:
        url = urljoin(self.base_url, "tools")
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        ...
    except Exception as e:
        logger.error(f"Failed to list MCP tools: {e}")
        raise MCPClientError(f"Failed to list tools: {str(e)}") from e
```

**Improved**:
```python
def list_tools(self) -> list[dict[str, Any]]:
    try:
        url = f"{self.base_url}tools"  # Direct construction (no urljoin ambiguity)
        logger.debug(f"📋 Fetching tools from: {url}")
        
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        
        tools = response.json()
        logger.info(f"✅ Discovered {len(tools)} tools from MCP service: {[t.get('name') for t in tools][:5]}")
        return tools
        
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ Cannot connect to MCP service at {self.base_url}: {e}")
        raise MCPClientError(f"MCP service connection failed: {str(e)}") from e
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ MCP service returned HTTP error: {e.response.status_code} {e.response.reason}")
        logger.error(f"   URL attempted: {e.response.url}")
        logger.error(f"   Response: {e.response.text[:200]}")
        raise MCPClientError(f"Failed to list tools: {str(e)}") from e
    except Exception as e:
        logger.error(f"❌ Unexpected error fetching MCP tools: {e}", exc_info=True)
        raise MCPClientError(f"Failed to list tools: {str(e)}") from e
```

---

### Fix #4: Fail Fast Instead of Silent Degradation
**File**: [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py#L147)

**Current**:
```python
if tools is None:
    logger.info(
        "🔌 Connecting to Superset MCP service on localhost:5008 "
        "to discover available tools..."
    )
    tools = get_mcp_tools()

    if not tools:
        logger.warning(
            "⚠️  No MCP tools available. Using agent without tools. "
            "Ensure Superset MCP service is running: "
            "docker compose up -d (requires --profile mcp)"
        )
        tools = []
```

**Option A - Allow graceful degradation (current) but add config flag**:
```python
REQUIRE_MCP_TOOLS = os.getenv("AI_REQUIRE_MCP_TOOLS", "false").lower() == "true"

if tools is None:
    logger.info(
        "🔌 Connecting to Superset MCP service to discover available tools..."
    )
    tools = get_mcp_tools()

    if not tools:
        if REQUIRE_MCP_TOOLS:
            raise ValueError(
                "❌ No MCP tools available but AI_REQUIRE_MCP_TOOLS=true. "
                "MCP service must be running and accessible."
            )
        else:
            logger.warning(
                "⚠️  No MCP tools available. Agent will run without tools. "
                "To require MCP tools, set AI_REQUIRE_MCP_TOOLS=true"
            )
        tools = []
```

**Option B - Always fail if tools unavailable** (strict mode):
```python
if tools is None:
    logger.info("🔌 Discovering MCP tools...")
    tools = get_mcp_tools()

    if not tools:
        raise ValueError(
            "❌ Failed to load MCP tools. Superset AI Agent requires MCP service. Ensure:\n"
            "  1. MCP service is running: docker compose --profile mcp up -d\n"
            "  2. MCP service port 5008 is accessible\n"
            "  3. Environment variable MCP_SERVICE_HOST is set correctly (default: 'superset-mcp' in Docker, 'localhost' locally)\n"
            "  4. MCP API endpoints are at http://host:5008/mcp/{tools,rpc}"
        )
```

---

## Testing & Validation

### Manual Testing Steps

**Step 1: Verify MCP Service Accessibility**
```bash
# Check if MCP service is running
docker ps | grep mcp

# Check if port 5008 is exposed
curl -I http://localhost:5008/health
# or in Docker network
curl -I http://superset-mcp:5008/health

# Check specific endpoint
curl http://superset-mcp:5008/mcp/tools
```

**Step 2: Verify URL Construction**
```python
from urllib.parse import urljoin

# Current (buggy)
base_url = "http://superset-mcp:5008/mcp"
url = urljoin(base_url, "tools")
print(url)  # Output: http://superset-mcp:5008/tools ❌

# Fixed
base_url = "http://superset-mcp:5008/mcp/"
url = urljoin(base_url, "tools")
print(url)  # Output: http://superset-mcp:5008/mcp/tools ✅
```

**Step 3: Test Agent with Tools**
```bash
# After applying Fix #1 and ensuring MCP service is running
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How many datasets do I have?"}'

# Response should include tool calls in logs:
# ✅ Loaded MCP tool: list_datasets
# ✅ Loaded MCP tool: list_charts
# etc.
```

---

## Configuration Checklist

Before deploying, verify:

- [ ] MCP service URL has trailing slash: `/mcp/`
- [ ] MCP service container is running and exposing port 5008
- [ ] `MCP_SERVICE_HOST` environment variable matches service hostname
- [ ] `/mcp/tools` endpoint is accessible from Superset container
- [ ] Docker services are running: `docker compose up -d` (superset-mcp is always included)
- [ ] Logs show "✅ Loaded X MCP tools" instead of "0 MCP tools"
- [ ] Agent uses tools for queries (verify in logs: "Invoking..." message shows tools list)

---

## Summary

### The Failure Chain:
1. **API receives chat query** ✅
2. **Agent initialization triggered** ✅
3. **LLM instance created** ✅
4. **MCP service URL constructed with bug** 🔴 → `http://superset-mcp:5008/tools` (missing `/mcp/`)
5. **HTTP 404 error returned** 🔴 → endpoint not found
6. **Error silently suppressed** ⚠️ → empty tool list returned
7. **Agent created without tools** ⚠️ → 0 tools loaded
8. **Query executed without tool access** 🔴 → uses default LLM knowledge only

### Immediate Actions:
1. **Apply URL fix** (add trailing slash to `base_url`)
2. **Verify MCP service running** (`docker compose --profile mcp up -d`)
3. **Test tool discovery** (curl `/mcp/tools` endpoint)
4. **Validate agent loads tools** (check logs for "✅ Loaded X MCP tools")

