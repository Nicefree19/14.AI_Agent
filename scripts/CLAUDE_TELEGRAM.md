# CLAUDE_TELEGRAM.md - Telegram Task Processing Instructions

## Execution Context

You are invoked by `telegram_executors.py` to process a Telegram message that did not match any keyword executor.
Your working directory is the project root: `D:\00.Work_AI_Tool\14.AI_Agent`.

## Available APIs

### Core Functions (`scripts/telegram/telegram_bot.py`)
- `check_telegram()` -> list of pending instructions with 24h context
- `combine_tasks(pending)` -> merged instruction per chat_id
- `create_working_lock(message_ids, instruction)` -> bool (atomic lock)
- `remove_working_lock()` -> None
- `reserve_memory_telegram(instruction, chat_id, timestamps, message_ids)` -> None
- `report_telegram(instruction, result_text, chat_id, timestamps, message_ids, files=[])` -> None
- `mark_done_telegram(message_ids)` -> None
- `load_memory()` -> list of past task_info dicts
- `get_task_dir(message_id)` -> Path

### Messaging (`scripts/telegram/telegram_sender.py`)
- `send_message_sync(chat_id, text)` -> None (max 4000 chars, auto-split)
- `send_files_sync(chat_id, message, file_paths)` -> None

## Task Processing Protocol

When you receive a task:
1. Parse the instruction to understand user intent
2. Use `load_memory()` to check for related previous work
3. Execute the task using P5 project tools as needed
4. Report results concisely in Korean
5. Include key findings, numbers, and actionable items

## P5 Project Tools

| Tool | Purpose | Command |
|------|---------|---------|
| `p5_email_triage.py` | Email classification | `process`, `queue`, `report` |
| `p5_daily_briefing.py` | Daily briefing | `generate` |
| `p5_issue_sync.py` | Google Sheets sync | `sync`, `push`, `status` |
| `p5_ocr_pipeline.py` | Attachment OCR | `process`, `link`, `health` |
| `p5_metrics.py` | Operations metrics | `generate` |
| `p5_risk_matrix.py` | Risk assessment | `generate` |

## Constraints

- Output files go to `telegram_data/tasks/msg_{id}/`
- Progress reports via `send_message_sync(chat_id, text)`
- Max message length 4000 chars (auto-split by sender)
- Always respond in Korean unless user writes in another language
- Be concise: prioritize actionable information over explanations
