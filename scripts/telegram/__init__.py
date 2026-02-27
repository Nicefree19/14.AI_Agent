"""
Telegram bot integration for P5 project management agent.

Two-Layer Architecture:
- Layer B (this package): Active Telegram polling + task execution
- Layer A (adapters/telegram_adapter.py): Passive message collection for message_daemon

Source: D:/00.Work_AI_Tool/16.mybot_ver2/
"""

from .telegram_bot import (
    check_telegram,
    combine_tasks,
    group_by_chat_id,
    create_working_lock,
    check_working_lock,
    remove_working_lock,
    reserve_memory_telegram,
    report_telegram,
    mark_done_telegram,
    load_memory,
    load_memory_for_task,
    load_index_summaries,
    load_project_context,
    get_task_dir,
    update_working_activity,
)
from .telegram_listener import fetch_new_messages
from .telegram_sender import send_message_sync, send_files_sync, run_async_safe
from .telegram_runner import run_telegram_task_once
from .telegram_executors import get_executor, EXECUTOR_MAP, list_executors

__all__ = [
    # telegram_bot
    "check_telegram",
    "combine_tasks",
    "group_by_chat_id",
    "create_working_lock",
    "check_working_lock",
    "remove_working_lock",
    "reserve_memory_telegram",
    "report_telegram",
    "mark_done_telegram",
    "load_memory",
    "load_memory_for_task",
    "load_index_summaries",
    "load_project_context",
    "get_task_dir",
    "update_working_activity",
    # telegram_listener
    "fetch_new_messages",
    # telegram_sender
    "send_message_sync",
    "send_files_sync",
    "run_async_safe",
    # telegram_runner
    "run_telegram_task_once",
    # telegram_executors
    "get_executor",
    "EXECUTOR_MAP",
    "list_executors",
]
