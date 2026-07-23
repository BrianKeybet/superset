# MCP Tool Discovery: Quick Reference Guide

## TL;DR - The Problem & Solution

### What Went Wrong ❌
Agent couldn't discover MCP tools because URL construction was broken:
- Base URL lacked trailing slash: `http://host:5008/mcp` → should be `http://host:5008/mcp/`
- `urljoin()` without trailing slash strips the last path segment
- Result: Requests went to `http://host:5008/tools` (404) instead of `http://host:5008/mcp/tools` (200)

### What Fixed It ✅
1. Added trailing slash to base_url
2. Replaced `urljoin()` with direct string formatting (`f"{base}path"`)
3. Improved error logging and agent initialization messages

### Files Changed
- `superset/ai_assistant/mcp_client.py` - URL fixes + enhanced logging
- `superset/ai_assistant/agent.py` - Better error messages + show actual hostname

---

## Quick Diagnosis

### How to Tell If Tools Are Loaded
```bash
# Check logs after sending chat request
docker compose logs superset | grep "Loaded.*MCP tool"

# ✅ Good:
"✅ Discovered 15 tools from MCP service"
"✅ Superset AI Agent initialized with 15 MCP tools"

# ❌ Bad:
"❌ No MCP tools available"
"✅ Superset AI Agent initialized with 0 MCP tools"
```

### How to Verify MCP Service is Accessible
```bash
# Test connectivity
curl -s http://localhost:5008/mcp/tools | jq 'length'
# Expected: A number (11, 15, 20, etc.), NOT an error

# If you get 404:
curl -s http://localhost:5008/tools | jq '.'
# ❌ This confirms the /mcp/ prefix is missing in your code
```

---

## Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| "404 Not Found for url: http://superset-mcp:5008/tools" | URL lacks `/mcp/` prefix | Apply fix #1: Add trailing slash to base_url |
| "No MCP tools available" | Service not running | `docker compose up -d` (superset-mcp is always included) |
| "Cannot connect to MCP service" | Hostname unreachable | Check MCP_SERVICE_HOST env var + network |
| Agent created with 0 tools | Error silently suppressed | Check logs for "Failed to list tools" |

---

## The Fix at a Glance

### Before
```python
# mcp_client.py line 85
self.base_url = f"http://{host}:{port}/mcp"  # ❌

# mcp_client.py line 233  
url = urljoin(self.base_url, "tools")   # ❌ Result: /tools (wrong!)
```

### After
```python
# mcp_client.py line 85
self.base_url = f"http://{host}:{port}/mcp/"  # ✅

# mcp_client.py line 233
url = f"{self.base_url}tools"  # ✅ Result: /mcp/tools (correct!)
```

---

## Testing the Fix

### 1-Minute Test
```bash
# Check if fix is applied
grep 'self.base_url = f.*mcp/' superset/ai_assistant/mcp_client.py

# Should output something with /mcp/" (trailing slash)
```

### 5-Minute Test
```bash
# 1. Ensure MCP is running (superset-mcp service is always included)
docker compose up -d
sleep 5

# 2. Test endpoint
curl -s http://localhost:5008/mcp/tools | jq length

# 3. Send chat query
curl -X POST http://localhost:8088/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "List datasets"}' | jq '.response'

# 4. Check logs
docker compose logs superset | grep "Loaded.*MCP" | head -1
```

### Full Test
```bash
# Run comprehensive test script
cat > /tmp/test_mcp_fix.sh << 'EOF'
#!/bin/bash
set -e

echo "🧪 Testing MCP Tool Discovery Fix...\n"

echo "1️⃣  Checking code fix..."
if grep -q 'self.base_url = f.*mcp/"' superset/ai_assistant/mcp_client.py; then
    echo "   ✅ Base URL has trailing slash"
else
    echo "   ❌ Base URL missing trailing slash"
    exit 1
fi

echo -e "\n2️⃣  Checking service status..."
if curl -s http://localhost:5008/health > /dev/null; then
    echo "   ✅ MCP service responding to /health"
else
    echo "   ❌ MCP service not responding"
    exit 1
fi

echo -e "\n3️⃣  Checking tools endpoint..."
tools=$(curl -s http://localhost:5008/mcp/tools | jq length)
if [ "$tools" -gt 0 ]; then
    echo "   ✅ Found $tools MCP tools"
else
    echo "   ❌ No tools found"
    exit 1
fi

echo -e "\n4️⃣  Checking agent initialization..."
logs=$(docker compose logs superset 2>/dev/null | grep "initialized with")
if echo "$logs" | grep -q "0 MCP tools"; then
    echo "   ❌ Agent has 0 tools"
    exit 1
elif echo "$logs" | tail -1 | grep -q "MCP tools"; then
    echo "   ✅ $(echo "$logs" | tail -1)"
else
    echo "   ⚠️  Cannot determine tool status from logs"
fi

echo -e "\n✅ All checks passed!"
EOF

bash /tmp/test_mcp_fix.sh
```

---

## Key Code Locations

| Issue | File | Lines | Fix |
|-------|------|-------|-----|
| Base URL construction | [mcp_client.py](superset/ai_assistant/mcp_client.py#L85) | 85 | Add `/` to end |
| Tool discovery | [mcp_client.py](superset/ai_assistant/mcp_client.py#L227) | 227-280 | Use f-string |
| Agent logging | [agent.py](superset/ai_assistant/agent.py#L170) | 170-210 | Show env vars |

---

## Deployment Checklist

- [ ] Code changes applied to `mcp_client.py` and `agent.py`
- [ ] Pre-commit validation passes: `pre-commit run --all-files`
- [ ] MCP service running: `docker compose up -d`
- [ ] Endpoint accessible: `curl http://localhost:5008/mcp/tools`
- [ ] Agent loads tools: `docker compose logs superset | grep "Loaded"`
- [ ] Test query works: `curl -X POST /api/v1/ai/chat ...`

---

## References

- **Full Analysis**: [MCP_TOOL_FAILURE_ANALYSIS.md](MCP_TOOL_FAILURE_ANALYSIS.md)
- **Implementation Guide**: [MCP_TOOL_FIX_IMPLEMENTATION.md](MCP_TOOL_FIX_IMPLEMENTATION.md)
- **Before/After Comparison**: [MCP_TOOL_FIX_SUMMARY.md](MCP_TOOL_FIX_SUMMARY.md)
- **Source Files**:
  - [superset/ai_assistant/mcp_client.py](superset/ai_assistant/mcp_client.py)
  - [superset/ai_assistant/agent.py](superset/ai_assistant/agent.py)

---

## Support

### If Still Not Working, Check:

1. **MCP service running?**
   ```bash
   docker ps | grep mcp
   ```

2. **Environment variables correct?**
   ```bash
   docker compose exec superset env | grep MCP
   ```

3. **Endpoint accessible from container?**
   ```bash
   docker compose exec superset curl http://superset-mcp:5008/mcp/tools
   ```

4. **Check error logs?**
   ```bash
   docker compose logs superset | grep ERROR
   docker compose logs mcp 2>/dev/null | tail -20
   ```

5. **Service health?**
   ```bash
   curl -s http://localhost:5008/health | jq .
   ```

### Debug Commands

```bash
# Show all MCP service details
docker ps --filter "name=mcp" --no-trunc

# Monitor logs in real-time
docker compose logs -f superset mcp

# Test URL from container
docker compose exec superset bash -c 'curl http://superset-mcp:5008/mcp/tools | jq'

# Show environment config
docker compose exec superset env | grep -E "MCP|LLM|AI"

# Restart MCP service
docker compose restart mcp
```

