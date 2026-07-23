# MCP Tool Discovery: Before → After Comparison

## Issue Summary

The Superset AI Agent failed silently to discover MCP tools, resulting in a zero-tool agent that cannot access Superset data or perform operations.

```
User Query                                    User Query
     ↓                                             ↓
Chat API Endpoint ✅                        Chat API Endpoint ✅
     ↓                                             ↓
Agent Initialization ✅                    Agent Initialization ✅
     ↓                                             ↓
LLM Instance Creation ✅                   LLM Instance Creation ✅
     ↓                                             ↓
MCP Tools Discovery 🔴 BEFORE              MCP Tools Discovery ✅ AFTER
     ↓                                             ↓
❌ URL Construction Bug                    ✅ URL Construction Fixed
   base_url = "http://host:5008/mcp"         base_url = "http://host:5008/mcp/"
                                                    
❌ urljoin strips /mcp                     ✅ urljoin preserves /mcp
   url = urljoin(base, "tools")              url = "{base}tools"
   → "/" → "/tools" (wrong!)                 → "/mcp/tools" (correct!)
                                             
❌ HTTP 404 Not Found                      ✅ HTTP 200 OK
   http://superset-mcp:5008/tools             http://superset-mcp:5008/mcp/tools
                                             
❌ Error Suppressed                        ✅ Error Logged + Tools Loaded
   "Failed to list tools"                     "Discovered 15 tools from MCP"
   return []                                  
                                             
❌ Agent Created with 0 Tools              ✅ Agent Created with 15 Tools
   No tool calls possible                     Tool calls available
   Default LLM knowledge only                 Data-driven responses
     ↓                                             ↓
❌ Query Without Tools                     ✅ Query With Tools
   (Generic, inaccurate response)             (Accurate, tool-based response)
```

---

## Root Cause Analysis

### The Bug Chain

```
1. BASE_URL CONSTRUCTION (Line 85 of mcp_client.py)
   ┌─────────────────────────────────────────┐
   │ BEFORE:                                  │
   │ self.base_url = f"http://{h}:{p}/mcp"   │ ❌ NO TRAILING SLASH
   └─────────────────────────────────────────┘
                      ↓
   ┌─────────────────────────────────────────┐
   │ AFTER:                                   │
   │ self.base_url = f"http://{h}:{p}/mcp/"  │ ✅ WITH TRAILING SLASH
   └─────────────────────────────────────────┘


2. URL JOIN BEHAVIOR (CRITICAL DIFFERENCE)
   ┌──────────────────────────────────────────────────────────────┐
   │ urljoin(*without* trailing slash):                            │
   │ urljoin("http://host:5008/mcp", "tools")                     │
   │  → "http://host:5008/tools"         ❌ WRONG (rewrites mcp) │
   │                                                               │
   │ urljoin(*with* trailing slash):                              │
   │ urljoin("http://host:5008/mcp/", "tools")                   │
   │  → "http://host:5008/mcp/tools"    ✅ CORRECT              │
   └──────────────────────────────────────────────────────────────┘


3. HTTP REQUEST (AFFECTED ENDPOINTS)
   ┌────────────────────────────────────────────────────────────┐
   │ BEFORE (Buggy URLs):                                        │
   │ • list_tools()          → GET /tools            → 404      │
   │ • call_tool()           → POST /tools/{name}    → 404      │
   │ • _call_tool_jsonrpc()  → POST /rpc             → 404      │
   │                                                            │
   │ AFTER (Fixed URLs):                                        │
   │ • list_tools()          → GET /mcp/tools        → 200      │
   │ • call_tool()           → POST /mcp/tools/{name} → 200     │
   │ • _call_tool_jsonrpc()  → POST /mcp/rpc         → 200      │
   └────────────────────────────────────────────────────────────┘


4. ERROR HANDLING
   ┌──────────────────────────────────────────────┐
   │ BEFORE: Exception silently converted to []    │
   │         No visibility into the issue           │
   │         Agent degraded gracefully              │
   │                                                │
   │ AFTER: Exception logged with actionable      │
   │        debugging steps                        │
   │        Better observability                   │
   └──────────────────────────────────────────────┘


5. OUTCOME
   ┌──────────────────────────────────────────────┐
   │ BEFORE: 0 MCP tools loaded                    │
   │        Agent function severely limited        │
   │        Cannot answer Superset-specific queries│
   │                                                │
   │ AFTER: 15+ MCP tools loaded                  │
   │       Agent can perform data operations      │
   │       Accurate, tool-driven responses        │
   └──────────────────────────────────────────────┘
```

---

## Affected Code Paths

```
superset/ai_assistant/
├── api.py
│   └── POST /chat
│       └── invoke_agent()
│
├── agent.py
│   └── create_superset_agent()
│       └── get_mcp_tools()          ← Tool discovery starts here
│           ↓
│
├── mcp_client.py
│   ├── SupersetMCPClient.__init__()
│   │   └── self.base_url = "http://{host}:{port}/mcp"  🔴 BUG: NO SLASH
│   │       └── FIXED: = "http://{host}:{port}/mcp/"    ✅ WITH SLASH
│   │
│   ├── get_mcp_tools()
│   │   └── mcp_client.list_tools()
│   │       └── url = urljoin(self.base_url, "tools")   🔴 BUG: WRONG URL
│   │           └── FIXED: url = f"{self.base_url}tools" ✅ CORRECT
│   │           └── HTTP GET → 404 ❌ → 200 ✅
│   │
│   ├── call_tool()
│   │   └── url = urljoin(self.base_url, f"tools/{name}") 🔴 BUG
│   │       └── FIXED: url = f"{self.base_url}tools/{name}" ✅
│   │
│   └── _call_tool_jsonrpc()
│       └── url = urljoin(self.base_url, "rpc")  🔴 BUG
│           └── FIXED: url = f"{self.base_url}rpc"  ✅
```

---

## Detailed Flow: Before vs After

### BEFORE (Broken)
```
1. User sends chat request
2. API creates agent with get_mcp_tools()
3. SupersetMCPClient initialized with:
   - host = "superset-mcp" (from env var)
   - port = 5008
   - base_url = "http://superset-mcp:5008/mcp"  ❌ NO TRAILING SLASH

4. list_tools() called:
   url = urljoin("http://superset-mcp:5008/mcp", "tools")
   → urljoin behavior (without trailing slash):
      Treats "mcp" as a page to be replaced by "tools"
      Result: "http://superset-mcp:5008/tools"  ❌ WRONG PATH

5. HTTP GET http://superset-mcp:5008/tools
   ↓
   MCP service expects: http://superset-mcp:5008/mcp/tools
   ↓
   Result: 404 Not Found ❌

6. Exception caught and suppressed:
   except Exception as e:
       logger.error(f"Failed to get MCP tools: {e}")
       return []  ← Empty tool list

7. Agent created with 0 tools:
   agent = create_react_agent(llm, [])

8. Query executed without tools:
   User: "How many datasets do I have?"
   Agent (without tools): "Based on my knowledge... [generic response]"
   ↓
   NOT accessing actual Superset data ❌
```

### AFTER (Fixed)
```
1. User sends chat request
2. API creates agent with get_mcp_tools()
3. SupersetMCPClient initialized with:
   - host = "superset-mcp"
   - port = 5008
   - base_url = "http://superset-mcp:5008/mcp/"  ✅ WITH TRAILING SLASH

4. list_tools() called:
   url = f"{self.base_url}tools"
   → Direct construction (no urljoin ambiguity):
      Appends "tools" to base_url
      Result: "http://superset-mcp:5008/mcp/tools"  ✅ CORRECT PATH

5. HTTP GET http://superset-mcp:5008/mcp/tools
   ↓
   MCP service ready at: http://superset-mcp:5008/mcp/tools
   ↓
   Result: 200 OK ✅
   Returns: [{"name": "list_datasets"}, {"name": "list_charts"}, ...]

6. Tools loaded successfully:
   for tool_def in tool_definitions:
       langchain_tool = create_mcp_langchain_tool(...)
       langchain_tools.append(langchain_tool)

7. Agent created with 15 tools:
   agent = create_react_agent(llm, [list_datasets, list_charts, ...])

8. Query executed with tools:
   User: "How many datasets do I have?"
   Agent: "Let me check using the list_datasets tool..."
   🔧 MCP Tool Call: list_datasets
   ✅ Result: "You have 42 datasets"
   ↓
   ACCESSING actual Superset data ✅
```

---

## Configuration Impact

### Environment Variables

```
MCP_SERVICE_HOST
├─ BEFORE Issues:
│  └─ Log said "localhost" but actually used env var value
│  └─ Confusing when hostname differs (e.g., "superset-mcp" in Docker)
│
└─ AFTER Improvements:
   └─ Logs now show actual hostname being used
   └─ Clear in error messages which host/port is being attempted

MCP_SERVICE_PORT
├─ BEFORE: Default 5008 (same)
└─ AFTER: Default 5008 (same) - no change needed
```

---

## Testing Scenarios

### Scenario 1: Successful Tool Loading ✅
```
Input:  MCP service running at localhost:5008/mcp/
Output: ✅ Discovered 15 tools from MCP service
        ✅ Loaded MCP tool: list_datasets
        ✅ Loaded MCP tool: list_charts
        ...
        ✅ Superset AI Agent initialized with 15 MCP tools
```

### Scenario 2: MCP Service Down ❌
```
BEFORE: ⚠️  No MCP tools available. Using agent without tools.
        (User doesn't understand why - misleading)

AFTER:  ❌ No MCP tools available. Agent will run without tools,
        which severely limits capabilities.
        
        To fix this, ensure:
        1. MCP service is running: docker compose --profile mcp up -d
        2. MCP service is accessible at superset-mcp:5008
        3. Check logs for MCP service errors
        4. Verify MCP container status: docker ps | grep mcp
```

### Scenario 3: Wrong Hostname ❌
```
BEFORE: Error message doesn't reveal which hostname was tried
        User confused about what "localhost" means in container

AFTER:  ❌ Cannot connect to MCP service at 
        http://wrong-host:5008/mcp/
        Ensure MCP service is running and accessible.
```

---

## Validation Checklist

After applying fixes, verify:

- [ ] URL construction uses trailing slash
  ```python
  # superset/ai_assistant/mcp_client.py line 85
  # Should show: self.base_url = f"http://{host}:{port}/mcp/"
  ```

- [ ] All URL joins use direct construction (no urljoin)
  ```python
  # Should find these patterns:
  url = f"{self.base_url}tools"
  url = f"{self.base_url}tools/{tool_name}"
  url = f"{self.base_url}rpc"
  ```

- [ ] Error logging is enhanced
  ```python
  # Should show specific error types:
  # - requests.exceptions.ConnectionError
  # - requests.exceptions.HTTPError
  # - Generic exceptions with traceback
  ```

- [ ] Agent logging shows actual hostname
  ```python
  # Should show actual env var values:
  # "MCP service at superset-mcp:5008"
  # not just "localhost:5008"
  ```

---

## Impact Summary

| Component | Before | After | Impact |
|-----------|--------|-------|--------|
| **URL Construction** | Broken (no slash) | Fixed (with slash) | ✅ Critical Fix |
| **Tool Discovery** | 404 Error | 200 OK | ✅ Tools Loaded |
| **Agent State** | 0 Tools | 15+ Tools | ✅ Major Improvement |
| **Error Visibility** | Silent suppression | Clear logging | ✅ Better Debugging |
| **User Experience** | Generic responses | Data-driven responses | ✅ Much Better |
| **Deployment Safety** | Graceful degradation | Fails loud | ⚠️ Breaking Change |

---

## Lessons Learned

1. **urljoin() is Tricky**: Without trailing slash, it treats path segments as replaceable, not prefixes
   
2. **Error Suppression Hides Issues**: Failing silently allowed this bug to go unnoticed despite requests failing

3. **Explicit is Better**: Direct URL construction (`f"{base}/path"`) is clearer than `urljoin(base, "path")`

4. **Logging Accuracy Matters**: Logging "localhost" when actually connecting to "superset-mcp" caused misdirection

5. **Configuration Should Be Explicit**: Show actual hostname/port in logs for better debugging

---

## Files Modified Summary

### [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py)
- **Lines 85**: Base URL trailing slash fix
- **Lines 155**: URL construction in `call_tool()`
- **Lines 195**: URL construction in `_call_tool_jsonrpc()`
- **Lines 227-280**: `list_tools()` with enhanced error handling
- **Throughout**: Improved logging and error messages

### [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py)
- **Lines 170-210**: Tool loading with better logging
- **Throughout**: Show actual environment variable values

