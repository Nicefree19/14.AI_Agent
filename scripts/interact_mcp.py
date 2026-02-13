import subprocess
import json
import sys
import time
import os
import shutil


def main():
    # Executable path in .agent_venv
    executable = (
        r"d:\00.Work_AI_Tool\14.AI_Agent\.agent_venv\Scripts\notebooklm-mcp.exe"
    )
    if not os.path.exists(executable):
        print(f"Error: {executable} not found")
        return

    print(f"Launching {executable}...")

    # Start the MCP server process
    process = subprocess.Popen(
        [executable],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Merge stderr to stdout
        text=True,
        bufsize=0,  # Unbuffered
    )

    # JSON-RPC Initialize
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",  # MCP Protocol standard
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }

    # Send initialize
    print("Sending initialize...")
    msg = json.dumps(init_req)
    process.stdin.write(msg + "\n")
    process.stdin.flush()
    print(f"Sent: {msg}")

    # Read response loop
    print("Listening for response...")

    start_time = time.time()
    while time.time() - start_time < 5:
        line = process.stdout.readline()
        if line:
            print(f"Received: {line.strip()}")
            if "notebook" in line.lower() or "resources" in line.lower():
                print("Potential relevant data found!")
        else:
            time.sleep(0.1)

    # If we got init, send list

    # List resources
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}

    print("Sending resources/list...")
    process.stdin.write(json.dumps(list_req) + "\n")
    process.stdin.flush()

    # Read loop again
    start_time = time.time()
    while time.time() - start_time < 5:
        line = process.stdout.readline()
        if line:
            print(f"Received: {line.strip()}")
        time.sleep(0.1)

    print("Terminating...")
    process.terminate()


if __name__ == "__main__":
    main()
