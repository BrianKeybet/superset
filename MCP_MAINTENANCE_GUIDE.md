# MCP Tools - Maintenance & Extension Guide

## Quick Reference

### For Adding New Tools

1. **Create** your tool module (e.g., `superset/mcp_service/myfeature/tool/__init__.py`)
2. **Define** tools with `@tool()` decorator from `superset.core.mcp.core_mcp_injection`
3. **Add import** to `register_all_tools()` in `superset/mcp_service/app.py`:

```python
# In register_all_tools() function, add:
from superset.mcp_service.myfeature.tool import (  # noqa: F401
    my_tool,
    another_tool,
)
```

### For Debugging Tool Discovery

Check these instance IDs match:
```python
# In app.py - creation point
mcp = create_mcp_app()  # id: 0xABC123

# In get_mcp_tools() - agent access point
# Should log: FastMCP instance type: FastMCP (id: 0xABC123)  ← SAME!
```

If IDs don't match → separate instances → need to investigate import paths.

### Architecture Overview

```
FastMCP Singleton Pattern
────────────────────────────────────────

app.py (module level):
├─ mcp = create_mcp_app()           ← Single instance created
│
├─ register_all_tools()             ← Called immediately
│  └─ Imports all tool modules
│     └─ @tool decorators register  ← Tools added to mcp instance
│
└─ All code imports from app.py
   └─ Uses same mcp instance        ← Guaranteed same object


Agent's tool discovery:
────────────────────────────────────────

mcp_client.get_mcp_tools()
├─ Import mcp from app.py
├─ Call register_all_tools()    ← Idempotent, ensures registration
├─ Call get_registered_mcp_tools()
└─ Return to LangChain          ← Agent gets all 19 tools


Why This Works:
────────────────────────────────────────

1. ONE mcp instance created at app.py load time
2. Tools registered immediately via register_all_tools()
3. Any code importing from app.py gets the SAME instance
4. Agent calling register_all_tools() again is safe (idempotent)
5. Tool discovery sees all registered tools ✓
```

## Important Patterns

### ✅ DO - Register Tools This Way

```python
# In superset/mcp_service/myfeature/tool/__init__.py

from superset.mcp_service.app import mcp

@mcp.tool()  # Tool decorator - automatically registers with mcp
def my_tool(input_param: str) -> str:
    """Tool description for MCP."""
    return f"Result: {input_param}"

# Then add to register_all_tools() in app.py:
# from superset.mcp_service.myfeature.tool import my_tool
```

### ❌ DON'T - Recreate mcp Instance

```python
# BAD: Creates a different instance!
from fastmcp import FastMCP
new_mcp = FastMCP("MyServer")

@new_mcp.tool()  # Registers on DIFFERENT instance
def broken_tool():
    pass
```

### ✅ DO - Import mcp from Central Location

```python
# CORRECT: All code imports from same place
from superset.mcp_service.app import mcp  # Central instance

@mcp.tool()
def my_tool():
    pass
```

### ❌ DON'T - Rely on Implicit Registration

```python
# FRAGILE: Assumes tools are registered by import order
from superset.mcp_service.chart.tool import list_charts  # Happened to work

# Better: Ensure registration explicitly
from superset.mcp_service.app import register_all_tools
register_all_tools()  # Now guaranteed
```

## Testing Tool Registration

### Check If Tools Are Available

```python
# In Python REPL or script
from superset.mcp_service.app import get_registered_mcp_tools, register_all_tools

# Ensure registration
register_all_tools()

# Get tools
tools = get_registered_mcp_tools()
print(f"Found {len(tools)} tools")
for tool in tools:
    print(f"  • {tool.name}")
```

### Check Instance IDs Match

```python
# Check that all imports reference same instance
import sys

# Before any tool imports
from superset.mcp_service.app import mcp as app_mcp
print(f"app.py instance: id={id(app_mcp)}")

# In agent code
from superset.ai_assistant.mcp_client import get_mcp_tools
from superset.mcp_service.app import mcp as agent_mcp
print(f"agent.py instance: id={id(agent_mcp)}")

# Should be same!
assert id(app_mcp) == id(agent_mcp), "Different instances!"
```

## Common Issues & Solutions

### Issue: "0 MCP tools available"

**Symptom**: Agent logs show no tools

**Check list**:
1. ✓ `register_all_tools()` being called? (check logs for "🔧 Registering")
2. ✓ Same instance ID in logs? Check for matching `(id: 0xABC)`
3. ✓ Tool modules exist? Check `superset/mcp_service/{chart,dashboard,etc.}/tool/`
4. ✓ Tools added to `register_all_tools()`? Verify in app.py

**Solution**: Add the tool module import to `register_all_tools()` in app.py

### Issue: Import Errors When Loading Tools

**Symptom**: Error like `ImportError: cannot import name ...`

**Check list**:
1. ✓ Tool module path is correct
2. ✓ Tool function/class is exported from `__init__.py`
3. ✓ No circular imports with app.py
4. ✓ Dependencies installed

**Solution**: 
- Verify import path matches file structure
- Check that tool module doesn't import app.py at module level (circular dependency)

### Issue: Duplicate Tools or Tools Not Appearing

**Symptom**: Tool appears multiple times, or some tools missing

**Check list**:
1. ✓ Tools aren't imported twice in `register_all_tools()`
2. ✓ All tool modules are listed exactly once
3. ✓ No typos in import statements
4. ✓ Tools not dynamically filtered out

**Solution**:
- Review `register_all_tools()` for duplicates
- Check FastMCP version for visibility/filtering features
- Look for `enabled=False` or similar in tool definitions

## Monitoring & Observability

### Key Log Lines to Check

When agent starts, you should see:

```
# Step 1: Module initialization
📦 FastMCP instance created at initialization (id: 140234567890)

# Step 2: Tool registration at load
🔧 Registering MCP tools with instance (id: 140234567890)
✅ MCP tools registered successfully

# Step 3: Agent discovery
FastMCP instance type: FastMCP (id: 140234567890)
📋 Found 19 MCP tools (via direct in-process access)

# All IDs should match (140234567890 in example)
```

### Debug Logging Available

Enable debug logging to see more details:

```python
import logging
logging.getLogger('superset.mcp_service.app').setLevel(logging.DEBUG)
logging.getLogger('superset.ai_assistant.mcp_client').setLevel(logging.DEBUG)
```

This will show:
- `list_tools()` method attempts
- `.server.tools` access attempts  
- Fallback attribute searches
- Which strategy successfully retrieved tools

## Performance Notes

- `register_all_tools()` is **idempotent** - safe to call multiple times
- Python import caching means subsequent calls are fast
- Tool decorators execute once per import (Python handles caching)
- No circular dependency risk if tools don't import app.py at module level

## Future Improvements

### Potential Enhancements

1. **Lazy Tool Loading**: Load tools on-demand instead of all at once
2. **Tool Categories**: Organize tools by domain with tags
3. **Dynamic Tool Registration**: Allow plugins to register tools at runtime
4. **Tool Versioning**: Support multiple versions of same tool
5. **Tool Metrics**: Track tool usage, errors, latency

### If Moving to Client/Server Architecture

The current in-process design can be extended to:

```python
# Future: Run MCP as separate service
# from fastmcp.client import Client

# agent.py
# async def get_mcp_tools_remote():
#     client = Client("http://mcp-service:5008")
#     async with client:
#         tools = await client.list_tools()
#         return convert_to_langchain(tools)
```

The underlying tool registration strategy stays the same - this just changes how tools are accessed.

## References

- **FastMCP Docs**: Check official FastMCP documentation for latest API
- **Superset MCP Architecture**: See `AGENTS.md` for overview
- **This Guide**: Maintenance reference for tool registration and debugging
