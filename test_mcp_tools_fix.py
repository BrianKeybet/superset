#!/usr/bin/env python3
"""
Diagnostic script to verify the MCP tools fix.

This script tests:
1. That register_all_tools() can be called without errors
2. That get_registered_mcp_tools() returns tools
3. That get_mcp_tools() returns LangChain Tool objects
4. That the same FastMCP instance is used throughout
"""

import sys
import logging

logging.basicConfig(level=logging.DEBUG, format='%(levelname)8s | %(name)s | %(message)s')
logger = logging.getLogger(__name__)

def test_single_instance():
    """Test that we're using a single shared FastMCP instance."""
    logger.info("=" * 80)
    logger.info("TEST 1: Single Instance Verification")
    logger.info("=" * 80)
    
    from superset.mcp_service.app import mcp as instance1
    logger.info(f"Instance 1 imported from app.py: id={id(instance1)}")
    
    from superset.mcp_service.app import mcp as instance2
    logger.info(f"Instance 2 imported from app.py: id={id(instance2)}")
    
    if id(instance1) == id(instance2):
        logger.info("✅ PASS: Same instance across imports")
        return True
    else:
        logger.error("❌ FAIL: Different instances!")
        return False

def test_register_all_tools():
    """Test that register_all_tools() works without errors."""
    logger.info("=" * 80)
    logger.info("TEST 2: Tool Registration")
    logger.info("=" * 80)
    
    try:
        from superset.mcp_service.app import register_all_tools, mcp
        
        logger.info(f"FastMCP instance before registration: id={id(mcp)}")
        register_all_tools()
        logger.info(f"FastMCP instance after registration: id={id(mcp)}")
        logger.info("✅ PASS: register_all_tools() executed without errors")
        return True
    except Exception as e:
        logger.error(f"❌ FAIL: register_all_tools() raised exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_registered_tools():
    """Test that get_registered_mcp_tools() returns tools."""
    logger.info("=" * 80)
    logger.info("TEST 3: Get Registered Tools")
    logger.info("=" * 80)
    
    try:
        from superset.mcp_service.app import get_registered_mcp_tools, register_all_tools
        
        # Ensure registration is done
        register_all_tools()
        
        tools = get_registered_mcp_tools()
        logger.info(f"Found {len(tools)} registered tools")
        
        if tools:
            logger.info("Tool list:")
            for tool in tools[:5]:  # Show first 5
                tool_name = getattr(tool, 'name', str(tool))
                logger.info(f"  - {tool_name}")
            if len(tools) > 5:
                logger.info(f"  ... and {len(tools) - 5} more")
            logger.info("✅ PASS: get_registered_mcp_tools() returned tools")
            return True
        else:
            logger.error("❌ FAIL: get_registered_mcp_tools() returned empty list")
            return False
    except Exception as e:
        logger.error(f"❌ FAIL: Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_mcp_tools():
    """Test that get_mcp_tools() returns LangChain Tool objects."""
    logger.info("=" * 80)
    logger.info("TEST 4: Get MCP Tools (LangChain)")
    logger.info("=" * 80)
    
    try:
        from superset.ai_assistant.mcp_client import get_mcp_tools
        
        tools = get_mcp_tools()
        logger.info(f"Found {len(tools)} LangChain tools")
        
        if tools:
            logger.info("Tool list:")
            for tool in tools[:5]:  # Show first 5
                tool_name = getattr(tool, 'name', str(tool))
                logger.info(f"  - {tool_name}")
            if len(tools) > 5:
                logger.info(f"  ... and {len(tools) - 5} more")
            logger.info("✅ PASS: get_mcp_tools() returned LangChain Tool objects")
            return True
        else:
            logger.error("❌ FAIL: get_mcp_tools() returned empty list")
            return False
    except Exception as e:
        logger.error(f"❌ FAIL: Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    logger.info("🧪 MCP Tools Fix Diagnostic Tests")
    logger.info("")
    
    results = []
    
    # Run tests
    results.append(("Single Instance", test_single_instance()))
    results.append(("Tool Registration", test_register_all_tools()))
    results.append(("Get Registered Tools", test_get_registered_tools()))
    results.append(("Get MCP Tools", test_get_mcp_tools()))
    
    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info("")
    logger.info(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! The MCP tools fix is working.")
        return 0
    else:
        logger.error(f"⚠️  {total - passed} test(s) failed. Review the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
