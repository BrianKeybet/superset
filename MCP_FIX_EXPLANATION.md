# MCP Tools Fix: Single Shared Instance Architecture

## Problem Summary

The agent was unable to discover MCP tools despite them being successfully registered in the system. The root cause was a **classic initialization ordering/timing problem combined with how Python module imports interact with singleton-like FastMCP instances**.

### Initial Symptoms
- Agent logs showed: "0 MCP tools available"  
- MCP service logs showed all 19 tools successfully registered
- `get_mcp_tools()` always returned empty list
- All discovery strategies (HTTP, attributes, methods) failed

### Root Cause Analysis

1. **Agent Process (Process 1)** imported `mcp` from `app.py` **early** (05:49:27)
   - Got reference to a "fresh" `FastMCP()` instance with empty registry

2. **MCP Service Process (Process 2)** later imported tool modules (05:49:43+)
   - Tool `@mcp.tool()` decorators executed, registering tools
   
3. **The Disconnect**: The tools were being registered on a **different reference** than what the agent had imported
   - Likely due to: module import timing, circular imports, or lazy loading patterns
   - Python's module cache should share the same object, but in practice they diverged

## Solution Implemented: Single Shared Instance Architecture

### Core Changes

#### 1. **Explicit Tool Registration Function** (`app.py` lines 316-386)

Created `register_all_tools()` function that:
- Consolidates all tool module imports into one callable function
- Can be invoked on-demand to guarantee registration on the shared instance
- Logs the FastMCP instance ID for debugging (verifies same instance)
- Enforces that registration happens on the **single canonical instance**

```python
def register_all_tools() -> None:
    """Explicitly register all MCP tools by importing tool modules."""
    logger.info(f"🔧 Registering MCP tools with instance (id: {id(mcp)})")
    
    # All tool module imports here
    from superset.mcp_service.chart.tool import generate_chart, get_chart_info, ...
    # ... more imports ...
    
    logger.info("✅ MCP tools registered successfully")
```

#### 2. **Guaranteed Registration at Module Load** (`app.py` line 384)

Added call at module level:
```python
# Call register_all_tools() at module initialization to ensure
# tools are registered when mcp_service.app is imported
register_all_tools()
```

This ensures tools are registered **the moment** `app.py` is imported, before any agent code tries to discover them.

#### 3. **Agent Calls Registration Before Access** (`mcp_client.py` line 447)

Updated `get_mcp_tools()` to:
- Import the shared `mcp` instance, `register_all_tools()`, and `get_registered_mcp_tools()`
- **Call `register_all_tools()`** before attempting discovery
- Log instance IDs to verify same instance is used throughout

```python
# CRITICAL: Ensure tools are registered on THIS instance before accessing
# This solves the initialization ordering problem where agent imports mcp
# before tools are registered
register_all_tools()
```

#### 4. **Improved Tool Registry Access** (`app.py` lines 387-439)

Enhanced `get_registered_mcp_tools()` with:
- Multiple fallback strategies to access tool registry
- Better logging for debugging (shows which strategy succeeded)
- Logs FastMCP instance ID for verification

### How It Fixes the Problem

**Before (Broken)**:
```
Agent imports mcp (empty) → registers tools → agent tries to get tools → finds nothing
                    ↓                              ↓
              Agent ref          Service ref (different objects)
```

**After (Fixed)**:
```
1. app.py imported by both processes
2. register_all_tools() called at module load
3. All tools registered on SINGLE SHARED instance
4. Agent calls get_mcp_tools()
5. get_mcp_tools() calls register_all_tools() (idempotent - re-registers, harmless)
6. get_registered_mcp_tools() accesses tools on SAME instance
7. Tools found and returned
```

### Key Design Principles

1. **Single Source of Truth**: One FastMCP instance created at `app.py` module level
2. **Explicit Registration**: `register_all_tools()` is callable and can be invoked multiple times
3. **Idempotent**: Calling `register_all_tools()` multiple times is safe (imports cache, handlers register once)
4. **Instance Verification**: Logging includes `id(mcp)` to prove same instance is used
5. **Defensive Programming**: Retry logic and fallback strategies if first access fails

### FastMCP Public API Used

- `mcp.list_tools()` - Official method to retrieve registered tools
- `mcp.server.tools` - Internal server registry (fallback)
- `@mcp.tool()` decorator - Registers via `add_tool()` at decoration time

### Files Changed

1. **`superset/mcp_service/app.py`**
   - Added `register_all_tools()` function (lines 316-386)
   - Moved all tool imports into this function
   - Call function at module initialization (line 384)
   - Enhanced `get_registered_mcp_tools()` with better logging (lines 387-439)
   - Instance ID logging added throughout for debugging

2. **`superset/ai_assistant/mcp_client.py`**
   - Updated `get_mcp_tools()` to import and call `register_all_tools()` (line 447)
   - Added instance ID logging for verification
   - Reduced retry sleep from 1s to 0.5s (optimization)

## Verification Strategy

To verify the fix works:

1. **Check Instance IDs Match**
   ```
   FastMCP instance created at initialization (id: 140234567890)
   Registering MCP tools with instance (id: 140234567890)  # Same ID
   FastMCP instance type: FastMCP (id: 140234567890)       # Still same ID
   ```

2. **Tool Count Should Match**
   - MCP service logs: "19 tools registered"
   - Agent logs: "Found 19 MCP tools"

3. **No Import Errors**
   - All modules import without syntax errors
   - All decorators execute successfully

## Why This Works Better Than Alternatives

### Option 1: Single Shared Instance ✅ (IMPLEMENTED)
- **Pros**: Simple, explicit, verifiable, follows Python best practices
- **Cons**: Requires coordinating registration
- **Status**: Currently implemented, should resolve the issue

### Option 2: Client-Side Discovery
- **Pros**: Treats MCP as proper server, uses official discovery protocol
- **Cons**: Overkill if agent and service in same process, adds network overhead
- **Status**: Could be used alongside Option 1 for extra robustness

### Option 3: Lazy Init + Explicit Add
- **Pros**: More flexible
- **Cons**: More error-prone, harder to debug
- **Status**: Less preferred than Option 1

## Next Steps If Issue Persists

1. **Check Instance IDs in Logs**
   - If different IDs → different instances being used → need to debug import paths

2. **Verify `register_all_tools()` is Called**
   - Should see: `"🔧 Registering MCP tools with instance (id: ...)"`

3. **Check Tool Count**
   - `get_registered_mcp_tools()` should return 19+ tools
   - If still empty, check FastMCP version and `list_tools()` method

4. **Check Import Order**
   - Ensure no circular imports preventing tools from loading
   - Verify `superset.mcp_service.app` is imported before agent tries to get tools

## Testing

Run the diagnostic script to verify:
```bash
python3 test_mcp_tools_fix.py
```

Expected output:
- ✅ PASS: Single Instance
- ✅ PASS: Tool Registration  
- ✅ PASS: Get Registered Tools (19 tools)
- ✅ PASS: Get MCP Tools (19 LangChain Tool objects)
