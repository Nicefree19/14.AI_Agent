#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Claude CLI executor with PID tracking and timeout.

Called by p5_autoexecutor.bat to launch Claude Code CLI
with proper process management. Replaces direct `call` in bat.

Features:
  - PID tracking: writes launched process PID to lock file
  - Timeout enforcement: kills process after max runtime
  - Lock keepalive: periodically touches lock file to prevent stale detection
  - Retry: tries resume (-p -c) first, then new session (-p)

Exit codes:
  0: Success
  1: Launch failure
  124: Timeout (process killed)
  Other: Claude CLI exit code

Usage:
  python claude_executor.py --claude-exe <path> --spf <path> --lockfile <path> --log <path> --timeout 1800
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time

# Base prompt for Claude CLI (context injected dynamically)
_PROMPT_BASE = (
    "Telegram message check and process. "
    "All APIs are in scripts/telegram/telegram_bot.py, "
    "sending uses scripts/telegram/telegram_sender.py send_message_sync(). "
    "If new messages: "
    "1) check_telegram() to check, "
    "2) combine_tasks() to merge, "
    "3) send_message_sync() for immediate reply, "
    "4) create_working_lock(), "
    "5) reserve_memory_telegram(), "
    "6) load_memory_for_task(instruction) to review relevant past work, "
    "7) execute task (report progress via send_message_sync()), "
    "8) report_telegram(), "
    "9) mark_done_telegram(), "
    "10) remove_working_lock(). "
    "After task completion, ask user if there are more tasks, "
    "then wait 3 minutes checking for new telegram messages; "
    "if found continue processing (repeat this loop until user "
    "stops or no response), then exit completely. "
    "When reporting progress via telegram, include key details and issues concisely."
)


def _build_prompt() -> str:
    """동적 프롬프트 생성: 프로젝트 컨텍스트 + 작업 이력 요약 주입."""
    try:
        # 절대 경로 기준 import (bat에서 프로젝트 루트로 pushd 후 실행)
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from scripts.telegram.telegram_bot import load_project_context, load_index_summaries
    except ImportError:
        return _PROMPT_BASE

    parts = [_PROMPT_BASE]

    # 프로젝트 컨텍스트 (~200-400 tokens)
    project_ctx = load_project_context()
    if project_ctx:
        parts.append(f"\n\n[프로젝트 컨텍스트]\n{project_ctx}")

    # 작업 이력 요약 (~300-500 tokens)
    summaries = load_index_summaries(limit=15)
    if summaries and summaries != "이전 작업 이력 없음.":
        parts.append(f"\n\n[최근 작업 이력]\n{summaries}")

    return "".join(parts)


def _touch_lockfile(lockfile: str, pid: int, interval: int, stop_event: threading.Event) -> None:
    """Periodically re-write lock file to prevent stale detection by the bat guard."""
    while not stop_event.is_set():
        stop_event.wait(interval)
        if stop_event.is_set():
            break
        try:
            with open(lockfile, "w", encoding="utf-8") as f:
                f.write(f"pid={pid}\n")
        except OSError:
            pass


def _execute_with_timeout(
    claude_exe: str,
    spf: str,
    prompt: str,
    log_path: str,
    lockfile: str,
    timeout_sec: int,
    resume: bool = True,
) -> tuple[int | None, int]:
    """
    Launch Claude CLI, track PID in lock file, enforce timeout.

    Args:
        claude_exe: Path to claude.exe or claude.cmd
        spf: Path to system prompt file (CLAUDE.md)
        prompt: Instruction text for Claude CLI
        log_path: Path to append stdout/stderr
        lockfile: Path to lock file for PID storage
        timeout_sec: Maximum seconds before kill
        resume: If True, use -c flag for session resume

    Returns:
        (pid, exit_code) tuple. pid=None on launch failure.
    """
    # Build command as argument list (shell=False for safety)
    cmd = [claude_exe, "-p"]
    if resume:
        cmd.append("-c")
    cmd.extend([
        "--dangerously-skip-permissions",
        "--append-system-prompt-file", spf,
        prompt,
    ])

    log_fh = open(log_path, "a", encoding="utf-8")

    try:
        proc = subprocess.Popen(
            cmd,
            shell=False,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        log_fh.write(f"[ERROR] Claude CLI launch failed: {e}\n")
        log_fh.close()
        return None, 1

    # Write PID to lock file
    try:
        with open(lockfile, "w", encoding="utf-8") as f:
            f.write(f"pid={proc.pid}\n")
    except OSError:
        pass

    # Start keepalive thread (re-writes lock every 5 min to prevent stale detection)
    stop_event = threading.Event()
    keeper = threading.Thread(
        target=_touch_lockfile,
        args=(lockfile, proc.pid, 300, stop_event),
        daemon=True,
    )
    keeper.start()

    # Wait with timeout
    try:
        ec = proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        # Kill process tree
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_fh.write(f"\n[TIMEOUT] Claude CLI killed after {timeout_sec}s (PID={proc.pid})\n")
        ec = 124
    finally:
        stop_event.set()
        keeper.join(timeout=5)
        log_fh.close()

    return proc.pid, ec


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude CLI executor with PID tracking and timeout")
    parser.add_argument("--claude-exe", required=True, help="Path to claude.exe or claude.cmd")
    parser.add_argument("--spf", required=True, help="Path to system prompt file")
    parser.add_argument("--lockfile", required=True, help="Path to lock file for PID storage")
    parser.add_argument("--log", required=True, help="Path to log file")
    parser.add_argument("--timeout", type=int, default=1800, help="Max runtime in seconds (default: 1800)")
    args = parser.parse_args()

    # Phase 1: Try resume (session continuation with -c flag)
    pid, ec = _execute_with_timeout(
        claude_exe=args.claude_exe,
        spf=args.spf,
        prompt=_build_prompt(),
        log_path=args.log,
        lockfile=args.lockfile,
        timeout_sec=args.timeout,
        resume=True,
    )

    # Phase 2: If resume failed (non-zero, non-timeout), try new session
    if ec != 0 and ec != 124:
        with open(args.log, "a", encoding="utf-8") as f:
            f.write(f"[INFO] Resume failed (EC={ec}). Starting new session...\n")

        pid, ec = _execute_with_timeout(
            claude_exe=args.claude_exe,
            spf=args.spf,
            prompt=_build_prompt(),
            log_path=args.log,
            lockfile=args.lockfile,
            timeout_sec=args.timeout,
            resume=False,
        )

    return ec


if __name__ == "__main__":
    sys.exit(main())
