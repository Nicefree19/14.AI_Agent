#!/usr/bin/env python3
"""
NotebookLM MCP Wrapper Script
Filters out ASCII banner and non-JSON output to prevent JSON-RPC errors.
"""
import sys
import os
import subprocess

# Ensure unbuffered output
os.environ["PYTHONUNBUFFERED"] = "1"


def is_json_line(line: str) -> bool:
    """Check if line looks like JSON-RPC message."""
    stripped = line.strip()
    if not stripped:
        return False
    # JSON-RPC messages start with { and end with }
    return stripped.startswith("{") and stripped.endswith("}")


def main():
    # Get the notebooklm-mcp executable path
    # Using uv tool run to execute it
    cmd = ["uv", "tool", "run", "notebooklm-mcp"]

    process = subprocess.Popen(
        cmd,
        stdin=sys.stdin,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        bufsize=1,
        universal_newlines=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    try:
        # Filter stdout - only pass JSON lines
        for line in process.stdout:
            if is_json_line(line):
                # Write valid JSON to stdout
                sys.stdout.write(line)
                sys.stdout.flush()
            else:
                # Send non-JSON (banners, logs) to stderr
                sys.stderr.write(f"[FILTERED] {line}")
                sys.stderr.flush()
    except KeyboardInterrupt:
        process.terminate()
    finally:
        process.wait()
        sys.exit(process.returncode or 0)


if __name__ == "__main__":
    main()
