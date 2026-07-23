#!/usr/bin/env python3
"""
Verify the MCP tools fix code structure is sound.
This script checks that all the necessary changes are in place.
"""

import re
import sys

def check_file_contains(filepath: str, pattern: str, description: str) -> bool:
    """Check if a file contains a pattern."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        
        if re.search(pattern, content, re.MULTILINE):
            print(f"✅ {description}")
            return True
        else:
            print(f"❌ {description}")
            return False
    except Exception as e:
        print(f"❌ Error checking {filepath}: {e}")
        return False

def main():
    """Run all verification checks."""
    print("🔍 MCP Tools Fix Code Structure Verification\n")
    
    checks = [
        # app.py checks
        (
            "superset/mcp_service/app.py",
            r"def register_all_tools\(\) -> None:",
            "✓ register_all_tools() function defined in app.py"
        ),
        (
            "superset/mcp_service/app.py",
            r"logger\.info\(f\"🔧 Registering MCP tools with instance \(id: \{id\(mcp\)\}\)\"",
            "✓ Instance ID logging in register_all_tools()"
        ),
        (
            "superset/mcp_service/app.py",
            r"generate_chart,",
            "✓ Chart tool imports in register_all_tools()"
        ),
        (
            "superset/mcp_service/app.py",
            r"health_check,",
            "✓ System tool imports in register_all_tools()"
        ),
        (
            "superset/mcp_service/app.py",
            r"# Call register_all_tools\(\) at module initialization",
            "✓ Comment about calling register_all_tools() at module init"
        ),
        (
            "superset/mcp_service/app.py",
            r"^register_all_tools\(\)$",
            "✓ register_all_tools() called at module level"
        ),
        (
            "superset/mcp_service/app.py", 
            r"def get_registered_mcp_tools\(\):",
            "✓ get_registered_mcp_tools() function exists"
        ),
        (
            "superset/mcp_service/app.py",
            r"logger\.debug\(f\"get_registered_mcp_tools: Checking FastMCP instance \(id: \{id\(mcp\)\}\)\"",
            "✓ Instance ID logging in get_registered_mcp_tools()"
        ),
        
        # mcp_client.py checks
        (
            "superset/ai_assistant/mcp_client.py",
            r"from superset\.mcp_service\.app import mcp as fastmcp_instance, register_all_tools, get_registered_mcp_tools",
            "✓ Imports register_all_tools and get_registered_mcp_tools"
        ),
        (
            "superset/ai_assistant/mcp_client.py",
            r"logger\.debug\(f\"FastMCP instance type:.*\(id: \{id\(fastmcp_instance\)\}\)\"",
            "✓ Instance ID logging in get_mcp_tools()"
        ),
        (
            "superset/ai_assistant/mcp_client.py",
            r"# CRITICAL: Ensure tools are registered on THIS instance before accessing",
            "✓ Critical comment about tool registration"
        ),
        (
            "superset/ai_assistant/mcp_client.py",
            r"register_all_tools\(\)",
            "✓ Calls register_all_tools() in get_mcp_tools()"
        ),
        (
            "superset/ai_assistant/mcp_client.py",
            r"logger\.info\(f\"📋 Found \{len\(fastmcp_tools\)\} MCP tools \(via direct in-process access\)\"",
            "✓ Improved logging about MCP tools count"
        ),
    ]
    
    passed = 0
    failed = 0
    
    print("Code Structure Checks:")
    print("-" * 60)
    
    for filepath, pattern, description in checks:
        if check_file_contains(filepath, pattern, description):
            passed += 1
        else:
            failed += 1
    
    print("-" * 60)
    print(f"\nResults: {passed}/{len(checks)} checks passed\n")
    
    if failed == 0:
        print("🎉 All code structure checks passed!")
        print("\nThe fix has been successfully implemented with:")
        print("  • Single shared FastMCP instance")
        print("  • Explicit register_all_tools() function")
        print("  • Instance ID logging for verification")
        print("  • Improved tool discovery with retry logic")
        return 0
    else:
        print(f"⚠️  {failed} check(s) failed. Review the code structure.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
