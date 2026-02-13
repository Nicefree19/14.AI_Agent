import sys
import os

# Try to find the right module
modules = ["notebooklm_mcp", "notebooklm_mcp_server", "notebooklm"]

for mod_name in modules:
    try:
        m = __import__(mod_name)
        print(f"SUCCESS: Imported {mod_name}")
        print(f"File: {m.__file__}")
        print(f"Dir: {dir(m)}")
        # If it has submodules, print them
        if hasattr(m, "server"):
            print(f"Server submodule: {dir(m.server)}")
        if hasattr(m, "client"):
            print(f"Client submodule: {dir(m.client)}")
    except ImportError:
        print(f"Failed to import {mod_name}")
    except Exception as e:
        print(f"Error importing {mod_name}: {e}")
