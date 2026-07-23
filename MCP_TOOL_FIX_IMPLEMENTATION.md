# MCP Tool Discovery Failure - Implementation Guide

## Overview

This guide provides step-by-step instructions to resolve the MCP tool discovery failure in Apache Superset's AI Agent. The issue has been diagnosed and fixes have been implemented.

---

## Changes Implemented

### 1. **URL Construction Bug Fix** ✅ CRITICAL
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L85)

#### Problem:
```python
# BEFORE (Line 85 - BUG)
self.base_url = f"http://{host}:{port}/mcp"  # ❌ No trailing slash
```

When using `urljoin()` without a trailing slash, it treats the last path segment as replaceable:
```python
from urllib.parse import urljoin

# Buggy behavior:
urljoin("http://superset-mcp:5008/mcp", "tools")
# Result: "http://superset-mcp:5008/tools" ❌ WRONG (removes /mcp)

# Fixed behavior:
urljoin("http://superset-mcp:5008/mcp/", "tools")
# Result: "http://superset-mcp:5008/mcp/tools" ✅ CORRECT
```

#### Solution:
```python
# AFTER (Line 85 - FIXED)
self.base_url = f"http://{host}:{port}/mcp/"  # ✅ Added trailing slash
```

**Impact**: Affects all URL construction using `urljoin()` on the base_url:
- `list_tools()` endpoint: `/mcp/tools` ✅
- `call_tool()` endpoint: `/mcp/tools/{tool_name}` ✅
- `_call_tool_jsonrpc()` endpoint: `/mcp/rpc` ✅

---

### 2. **URL Construction in `list_tools()`** ✅
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L230)

#### Before:
```python
url = urljoin(self.base_url, "tools")  # Ambiguous, relies on trailing slash
```

#### After:
```python
url = f"{self.base_url}tools"  # Direct construction - no ambiguity
```

**Benefit**: More explicit and avoids urljoin quirks entirely.

---

### 3. **URL Construction in `call_tool()`** ✅
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L155)

#### Before:
```python
url = urljoin(self.base_url, f"tools/{tool_name}")
```

#### After:
```python
url = f"{self.base_url}tools/{tool_name}"
```

---

### 4. **URL Construction in `_call_tool_jsonrpc()`** ✅ 
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L195)

#### Before:
```python
url = urljoin(self.base_url, "rpc")
```

#### After:
```python
url = f"{self.base_url}rpc"
```

---

### 5. **Enhanced Error Logging in MCP Client Initialization** ✅
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L76)

#### Added:
```python
logger.debug(
    f"🔌 MCP Client initialized: base_url={self.base_url}, "
    f"host={host}, port={port}"
)

# Changed from warning to error for better visibility
logger.error(
    f"❌ MCP service not accessible at {self.base_url}. "
    f"Verify the following:\n"
    f"  1. MCP service container is running: docker ps | grep mcp\n"
    f"  2. Port {port} is exposed: docker port <mcp-container>\n"
    f"  3. Hostname '{host}' resolves correctly in your environment\n"
    f"  4. Service /health endpoint is accessible: "
    f"curl http://{host}:{port}/health\n"
    f"  5. Service /mcp/tools endpoint is accessible: "
    f"curl http://{host}:{port}/mcp/tools\n"
    f"  6. If using docker compose: docker compose --profile mcp up -d"
)
```

---

### 6. **Improved Error Handling in `list_tools()`** ✅
**File**: [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py#L227)

#### Added specific error handling:
```python
except requests.exceptions.ConnectionError as e:
    logger.error(
        f"❌ Cannot connect to MCP service at {self.base_url}: {e}. "
        f"Ensure MCP service is running and accessible."
    )
    raise MCPClientError(f"MCP service connection failed: {str(e)}") from e

except requests.exceptions.HTTPError as e:
    logger.error(
        f"❌ MCP service returned HTTP error: "
        f"{e.response.status_code} {e.response.reason}"
    )
    logger.error(f"   URL attempted: {e.response.url}")
    logger.error(f"   Response body: {e.response.text[:200]}")
    raise MCPClientError(
        f"Failed to list tools: HTTP {e.response.status_code}"
    ) from e
```

---

### 7. **Improved MCP Tool Loading in Agent** ✅
**File**: [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py#L170)

#### Before:
```python
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
```

#### After:
```python
import os
mcp_host = os.getenv("MCP_SERVICE_HOST", "localhost")
mcp_port = os.getenv("MCP_SERVICE_PORT", "5008")

logger.info(
    f"🔌 Discovering MCP tools from Superset MCP service at "
    f"{mcp_host}:{mcp_port}..."
)
tools = get_mcp_tools()

if not tools:
    logger.error(  # Changed: warning → error
        f"❌ No MCP tools available. Agent will run without tools, "
        f"which severely limits capabilities.\n\n"
        f"To fix this, ensure:\n"
        f"  1. MCP service is running: docker compose --profile mcp up -d\n"
        f"  2. MCP service is accessible at {mcp_host}:{mcp_port}\n"
        f"  3. Check logs for MCP service errors\n"
        f"  4. Verify MCP container status: docker ps | grep mcp"
    )
```

**Benefits**:
- Shows actual hostname being used (not always "localhost")
- Clearer error message
- Better actionable debugging steps

---

## Verification Checklist

After applying the fixes, verify each component:

- [ ] **URL Construction**: Verify `base_url` ends with `/`
  ```bash
  grep 'self.base_url = f' superset/ai_assistant/mcp_client.py | head -1
  # Expected: self.base_url = f"http://{host}:{port}/mcp/"
  ```

- [ ] **MCP Service Running**:
  ```bash
  docker ps | grep mcp
  # Expected: See "superset-mcp" container
  ```

- [ ] **Port Exposed**:
  ```bash
  docker port $(docker ps -q -f "name=mcp")
  # Expected: See port 5008 mapping
  ```

- [ ] **Service Accessible**:
  ```bash
  curl -s http://localhost:5008/health | head -20
  # Expected: HTTP response (200 or similar), not connection refused
  ```

- [ ] **Endpoint Exists**:
  ```bash
  curl -s http://localhost:5008/mcp/tools | jq 'length'
  # Expected: Number of tools available (e.g., 15, 20, etc.)
  ```

- [ ] **Agent Loads Tools**:
  ```bash
  # Check logs after sending chat request
  docker compose logs superset | grep "Loaded.*MCP tool"
  # Expected: "✅ Loaded 15 MCP tools"
  ```

---

## Testing the Fix

### Step 1: Ensure MCP Service is Running
```bash
cd /home/kapa-bi-02/superset

# Start services with MCP profile
docker compose --profile mcp up -d

# Wait for services to be healthy
sleep 10

# Verify MCP service is running
docker ps | grep mcp
```

### Step 2: Test URL Construction
```python
# Create a simple test script
cat > /tmp/test_mcp_urls.py << 'EOF'
from urllib.parse import urljoin

# Test the fixed URL construction
base_url = "http://superset-mcp:5008/mcp/"

test_cases = [
    ("tools", "http://superset-mcp:5008/mcp/tools"),
    ("tools/list_charts", "http://superset-mcp:5008/mcp/tools/list_charts"),
    ("rpc", "http://superset-mcp:5008/mcp/rpc"),
]

print("Testing URL construction with trailing slash:\n")
for path, expected in test_cases:
    result = urljoin(base_url, path)
    status = "✅" if result == expected else "❌"
    print(f"{status} urljoin('{base_url}', '{path}')")
    print(f"   Expected: {expected}")
    print(f"   Got:      {result}\n")
EOF

python /tmp/test_mcp_urls.py
```

### Step 3: Test MCP Endpoint Access
```bash
# Test each endpoint
echo "Testing MCP endpoints...\n"

echo "1. Health endpoint:"
curl -s http://localhost:5008/health | head -5

echo -e "\n2. Tools endpoint:"
curl -s http://localhost:5008/mcp/tools | jq 'length'

echo -e "\n3. Specific tool:"
curl -s http://localhost:5008/mcp/tools | jq '.[0].name'
```

### Step 4: Test Agent Tool Loading
```bash
# Send a test chat request
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How many datasets do I have?"}' \
  -s | jq '.response' | head -20

# Check logs for tool loading
docker compose logs superset | grep -E "(Loaded|MCP|tools)" | tail -20
```

**Expected Log Output**:
```
✅ Discovered 15 tools from MCP service: ['list_datasets', 'list_charts', ...]
✅ Loaded MCP tool: list_datasets
✅ Loaded MCP tool: list_charts
...
✅ Superset AI Agent initialized with 15 MCP tools: ...
```

---

## Troubleshooting

### Issue: "404 Not Found" for `/tools`
**Cause**: URL missing `/mcp/` prefix  
**Fix**: Ensure `base_url` has trailing slash

```bash
# Check the fix
grep 'self.base_url = f' superset/ai_assistant/mcp_client.py
# Should show: self.base_url = f"http://{host}:{port}/mcp/"
```

### Issue: "Connection refused" to `superset-mcp:5008`
**Cause**: MCP service not running or not exposed  
**Fix**: 
```bash
docker compose --profile mcp up -d
docker ps | grep mcp
```

### Issue: Agent shows "0 MCP tools"
**Causes**: (in order of likelihood)
1. MCP service not running → Check `docker ps`
2. Wrong hostname/port → Check `MCP_SERVICE_HOST`, `MCP_SERVICE_PORT`
3. Endpoint not at `/mcp/tools` → Test with curl
4. HTTP 404 error → Check logs: `docker compose logs superset | grep 404`

**Debugging**:
```bash
# Check environment variables
docker compose exec superset env | grep MCP

# Check connectivity
docker compose exec superset curl http://superset-mcp:5008/mcp/tools

# Check logs for errors
docker compose logs superset | grep ERROR | tail -10
docker compose logs mcp 2>/dev/null | tail -20
```

---

## Files Modified

1. **[superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py)**
   - Line 85: Added trailing slash to `base_url`
   - Line 155: Changed `call_tool()` to use direct URL construction
   - Line 195: Changed `_call_tool_jsonrpc()` to use direct URL construction
   - Line 230: Changed `list_tools()` to use direct URL construction
   - Enhanced error logging throughout

2. **[superset/ai_assistant/agent.py](superset/ai_assistant/agent.py#L170)**
   - Improved logging to show actual MCP hostname
   - Enhanced error messages with actionable debugging steps
   - Changed warning to error when tools unavailable

---

## Deployment Notes

### Pre-deployment Checklist
- [ ] All syntax errors fixed (files pass PEP-8 validation)
- [ ] Pre-commit checks pass: `pre-commit run --all-files`
- [ ] Type checking passes: `pre-commit run mypy`
- [ ] Tests pass: `pytest tests/ai_assistant/`

### Deployment Process
```bash
# 1. Stage changes
git add superset/ai_assistant/mcp_client.py superset/ai_assistant/agent.py

# 2. Run pre-commit validation
pre-commit run --all-files

# If there are auto-fixes, stage them
git add .

# 3. Commit with conventional commit message
git commit -m "fix(ai-assistant): correct MCP URL construction and improve error logging

- Add trailing slash to base_url for correct urljoin behavior
- Replace urljoin with direct URL construction for clarity
- Enhance error messages with actionable debugging steps
- Show actual MCP hostname in logs instead of hardcoded 'localhost'
- Change missing-tools warning to error for visibility

Fixes issue where agent failed to discover MCP tools due to:
1. urljoin stripping /mcp/ prefix without trailing slash
2. Misleading log messages about endpoint location
3. Silent error suppression"

# 4. Push changes
git push origin feature-mcp-fix
```

### Post-deployment Verification
```bash
# 1. Ensure services are running (superset-mcp is always included)
docker compose up -d

# 2. Monitor logs for tool loading
docker compose logs -f superset | grep -E "(MCP|tools|Loaded)"

# 3. Test with sample queries
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "List all datasets"}'

# 4. Verify tools are used in responses
docker compose logs superset | grep "🔧 MCP Tool Call"
```

---

## Related Documentation

- [MCP_TOOL_FAILURE_ANALYSIS.md](MCP_TOOL_FAILURE_ANALYSIS.md) - Detailed analysis of the failure
- [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py) - Agent creation and invocation
- [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py) - MCP service client
- [Docker Compose Configuration](docker-compose.yml) - MCP service setup

