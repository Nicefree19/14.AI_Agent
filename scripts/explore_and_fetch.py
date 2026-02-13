import sys

print("Exploring modules...")
try:
    import notebooklm_mcp

    print("SUCCESS: notebooklm_mcp")
    print(dir(notebooklm_mcp))
except ImportError:
    print("FAIL: notebooklm_mcp")
    try:
        import notebooklm_mcp_server

        print("SUCCESS: notebooklm_mcp_server")
        print(dir(notebooklm_mcp_server))
    except ImportError:
        print("FAIL: notebooklm_mcp_server")
