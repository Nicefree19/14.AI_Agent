"""
텔레그램 봇 통합 로직

기존 bot.py와 유사한 구조로 텔레그램 메시지 처리

주요 기능:
- check_telegram() - 새로운 명령 확인 (최근 24시간 대화 내역 포함)
- report_telegram() - 결과 전송 및 메모리 저장
- mark_done_telegram() - 처리 완료 표시
- load_memory() - 기존 메모리 로드 (bot.py와 공유)
- reserve_memory_telegram() - 작업 시작 시 메모리 예약
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from .telegram_sender import send_files_sync, run_async_safe
from enum import Enum

from .config import (
    TELEGRAM_DATA_DIR,
    MESSAGES_FILE as _CFG_MESSAGES_FILE,
    TASKS_DIR as _CFG_TASKS_DIR,
    INDEX_FILE as _CFG_INDEX_FILE,
    WORKING_LOCK_FILE as _CFG_WORKING_LOCK_FILE,
    NEW_INSTRUCTIONS_FILE as _CFG_NEW_INSTRUCTIONS_FILE,
    WORKING_LOCK_TIMEOUT,
    is_enabled,
)


# ═══════════════════════════════════════════════════════════════
#  메시지 상태 머신 (feature flag: state_machine)
# ═══════════════════════════════════════════════════════════════


class MessageState(str, Enum):
    """7단계 메시지 처리 상태."""
    PENDING = "pending"              # 수신됨, 미처리
    TRIAGED = "triaged"              # classify_message() 완료
    CONTEXT_READY = "context_ready"  # combine_tasks() + 24h 컨텍스트
    EXECUTING = "executing"          # executor 시작
    COMPLETED = "completed"          # report_telegram() 성공
    FAILED = "failed"                # 예외 발생
    CLOSED = "closed"                # mark_done_telegram() 호출


def _update_message_state(
    message_id: int,
    new_state: MessageState,
    *,
    extra: dict | None = None,
) -> None:
    """메시지 상태를 telegram_messages.json에 기록.

    feature flag "state_machine" OFF → no-op.
    """
    if not is_enabled("state_machine"):
        return

    try:
        messages = _load_messages_file()
        for msg in messages:
            if msg.get("message_id") == message_id:
                msg["state"] = new_state.value
                msg["state_updated_at"] = datetime.now().isoformat()
                if extra:
                    msg.setdefault("state_history", []).append({
                        "state": new_state.value,
                        "at": datetime.now().isoformat(),
                        **extra,
                    })
                break
        _atomic_json_write(MESSAGES_FILE, messages)
    except Exception:
        # 상태 기록 실패가 본 작업을 중단시키면 안 됨
        pass


def _load_messages_file() -> list:
    """telegram_messages.json 로드. 파일 없으면 빈 리스트."""
    if not os.path.exists(MESSAGES_FILE):
        return []
    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


_BASE_DIR = str(TELEGRAM_DATA_DIR)

MESSAGES_FILE = str(_CFG_MESSAGES_FILE)
TASKS_DIR = str(_CFG_TASKS_DIR)
INDEX_FILE = str(_CFG_INDEX_FILE)
WORKING_LOCK_FILE = str(_CFG_WORKING_LOCK_FILE)
NEW_INSTRUCTIONS_FILE = str(_CFG_NEW_INSTRUCTIONS_FILE)
PROJECT_CONTEXT_FILE = os.path.join(_BASE_DIR, "project_context.md")
OBSIDIAN_WORKLOG_DIR = str(Path(__file__).resolve().parent.parent.parent / "ResearchVault" / "P5-Project" / "05-WorkLog")


def _atomic_json_write(filepath: str, data) -> None:
    """
    원자적 JSON 쓰기 — 크래시/디스크풀 안전.

    임시파일에 쓴 뒤 os.replace()로 원자적 교체.
    중간 크래시 시에도 원본 파일이 손상되지 않음.
    """
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, filepath)


def load_telegram_messages():
    """telegram_messages.json 로드 (손상 시 .bak 복구 시도)"""
    default = {"messages": [], "last_update_id": 0}
    if not os.path.exists(MESSAGES_FILE):
        return default

    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"⚠️ telegram_messages.json 손상: {e}")
        # 백업에서 복구 시도
        bak = MESSAGES_FILE + ".bak"
        if os.path.exists(bak):
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print("✅ .bak에서 복구 성공")
                _atomic_json_write(MESSAGES_FILE, data)
                return data
            except Exception:
                pass
        # 손상 파일을 .corrupt로 보존
        corrupt = MESSAGES_FILE + f".corrupt.{int(time.time())}"
        try:
            os.replace(MESSAGES_FILE, corrupt)
            print(f"⚠️ 손상 파일 보존: {corrupt}")
        except OSError:
            pass
        return default
    except OSError as e:
        print(f"⚠️ telegram_messages.json 읽기 오류: {e}")
        return default


def save_telegram_messages(data):
    """telegram_messages.json 저장 (원자적 쓰기 + .bak 롤링 백업)"""
    # 기존 파일을 .bak으로 백업 (복구용)
    if os.path.exists(MESSAGES_FILE):
        try:
            bak = MESSAGES_FILE + ".bak"
            import shutil
            shutil.copy2(MESSAGES_FILE, bak)
        except OSError:
            pass
    _atomic_json_write(MESSAGES_FILE, data)


def save_bot_response(chat_id, text, reply_to_message_ids, files=None):
    """
    봇 응답을 telegram_messages.json에 저장 (대화 컨텍스트 유지)

    Args:
        chat_id: 채팅 ID
        text: 봇 응답 메시지
        reply_to_message_ids: 응답 대상 메시지 ID (리스트)
        files: 전송한 파일 리스트 (선택)
    """
    data = load_telegram_messages()

    # 봇 응답 메시지 데이터
    bot_message = {
        "message_id": f"bot_{reply_to_message_ids[0]}",  # 봇 메시지 ID (고유)
        "type": "bot",  # 메시지 타입
        "chat_id": chat_id,
        "text": text,
        "files": files or [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reply_to": reply_to_message_ids,  # 어떤 메시지에 대한 응답인지
        "processed": True  # 봇 메시지는 항상 processed
    }

    data["messages"].append(bot_message)
    save_telegram_messages(data)

    print(f"📝 봇 응답 저장 완료 (reply_to: {reply_to_message_ids})")


def check_working_lock():
    """
    작업 잠금 파일 확인. 마지막 활동(경과 보고) 기준 30분 타임아웃.

    Returns:
        dict or None: 잠금 정보 (존재하면) 또는 None
        특수 케이스: {"stale": True, ...} - 스탈 작업 (재시작 필요)
    """
    if not os.path.exists(WORKING_LOCK_FILE):
        return None

    try:
        with open(WORKING_LOCK_FILE, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
    except Exception as e:
        print(f"⚠️ working.json 읽기 오류: {e}")
        return None

    # 마지막 활동 시각 확인 (없으면 started_at 사용)
    last_activity_str = lock_info.get("last_activity", lock_info.get("started_at"))

    try:
        last_activity = datetime.strptime(last_activity_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        idle_seconds = (now - last_activity).total_seconds()

        # 스탈네스 확인: 마지막 활동으로부터 30분 이상 경과
        if idle_seconds > WORKING_LOCK_TIMEOUT:
            print(f"⚠️ 스탈 작업 감지 (마지막 활동: {int(idle_seconds/60)}분 전)")
            print(f"   메시지 ID: {lock_info.get('message_id')}")
            print(f"   지시사항: {lock_info.get('instruction_summary')}")

            # 스탈 플래그 추가하여 반환 (삭제하지 않음 - 재시작 필요)
            lock_info["stale"] = True
            return lock_info

        # 활동 중인 작업
        print(f"ℹ️ 작업 진행 중 (마지막 활동: {int(idle_seconds/60)}분 전)")
        return lock_info

    except Exception as e:
        print(f"⚠️ 타임스탬프 파싱 오류: {e}")
        # 파싱 실패 시 파일 수정 시각으로 fallback
        lock_age = time.time() - os.path.getmtime(WORKING_LOCK_FILE)
        if lock_age > WORKING_LOCK_TIMEOUT:
            try:
                os.remove(WORKING_LOCK_FILE)
            except OSError:
                pass
            return None
        return lock_info


def create_working_lock(message_id, instruction, execution_path="unknown"):
    """
    원자적으로 작업 잠금 파일 생성. 이미 존재하면 False 반환.

    Args:
        message_id: 메시지 ID (또는 리스트)
        instruction: 지시사항
        execution_path: 실행 경로 식별자 ("autoexecutor", "telegram_runner", "daily" 등)

    Returns:
        bool: 생성 성공 여부
    """
    # message_id가 리스트인 경우 (여러 메시지 합산)
    if isinstance(message_id, list):
        message_ids = message_id
        msg_id_str = f"{', '.join(map(str, message_ids))} (합산 {len(message_ids)}개)"
    else:
        message_ids = [message_id]
        msg_id_str = str(message_id)

    summary = instruction.replace("\n", " ")[:50]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lock_data = {
        "message_id": message_ids[0] if len(message_ids) == 1 else message_ids,
        "instruction_summary": summary,
        "started_at": now_str,
        "last_activity": now_str,
        "count": len(message_ids),
        "execution_path": execution_path,
    }

    try:
        with open(WORKING_LOCK_FILE, "x", encoding="utf-8") as f:
            json.dump(lock_data, f, ensure_ascii=False, indent=2)
        print(f"🔒 작업 잠금 생성: message_id={msg_id_str}")
        # 상태 머신: EXECUTING
        for mid in message_ids:
            _update_message_state(mid, MessageState.EXECUTING)
        return True
    except FileExistsError:
        print(f"⚠️ 잠금 파일 이미 존재. 다른 작업이 진행 중입니다.")
        return False


def update_working_activity():
    """
    작업 잠금의 마지막 활동 시각 갱신 (경과 보고 시 호출)

    중간 경과 보고(send_message_sync)를 할 때마다 호출하여
    작업이 여전히 진행 중임을 표시합니다.
    """
    if not os.path.exists(WORKING_LOCK_FILE):
        return

    try:
        with open(WORKING_LOCK_FILE, "r", encoding="utf-8") as f:
            lock_data = json.load(f)

        # last_activity 갱신
        lock_data["last_activity"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        _atomic_json_write(WORKING_LOCK_FILE, lock_data)

    except Exception as e:
        print(f"⚠️ working.json 활동 갱신 오류: {e}")


def check_new_messages_during_work():
    """
    작업 중 새 메시지 확인 (working.json이 있을 때만)

    Returns:
        list: 새로운 메시지 리스트
        [
            {
                "message_id": int,
                "instruction": str,
                "timestamp": str,
                "chat_id": int,
                "user_name": str,
                "detected_at": str
            },
            ...
        ]
    """
    # working.json이 없으면 작업 중이 아니므로 확인 안 함
    if not os.path.exists(WORKING_LOCK_FILE):
        return []

    try:
        with open(WORKING_LOCK_FILE, "r", encoding="utf-8") as f:
            lock_info = json.load(f)
    except Exception:
        return []

    # 스탈 작업이면 확인 안 함
    if lock_info.get("stale"):
        return []

    # 현재 처리 중인 메시지 ID
    current_message_ids = lock_info.get("message_id")
    if not isinstance(current_message_ids, list):
        current_message_ids = [current_message_ids]

    # 🆕 이미 new_instructions.json에 저장된 메시지 ID 확인
    already_saved = load_new_instructions()
    saved_message_ids = {inst["message_id"] for inst in already_saved}

    # Telegram API에서 새 메시지 수집
    _poll_telegram_once()

    # 새 메시지 확인
    data = load_telegram_messages()
    messages = data.get("messages", [])

    new_messages = []
    for msg in messages:
        # 이미 처리된 메시지 제외
        if msg.get("processed", False):
            continue

        # 현재 처리 중인 메시지 제외
        if msg["message_id"] in current_message_ids:
            continue

        # 🆕 이미 저장된 메시지 제외 (중복 알림 방지)
        if msg["message_id"] in saved_message_ids:
            continue

        # 새 메시지 발견!
        new_messages.append({
            "message_id": msg["message_id"],
            "instruction": msg["text"],
            "timestamp": msg["timestamp"],
            "chat_id": msg["chat_id"],
            "user_name": msg["first_name"],
            "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    return new_messages


def save_new_instructions(new_messages):
    """
    새 지시사항을 파일에 저장

    Args:
        new_messages: check_new_messages_during_work()가 반환한 메시지 리스트
    """
    if not new_messages:
        return

    # 기존 파일 읽기 (있으면)
    if os.path.exists(NEW_INSTRUCTIONS_FILE):
        try:
            with open(NEW_INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"instructions": []}
    else:
        data = {"instructions": []}

    # 새 메시지 추가 (중복 제거)
    existing_ids = {inst["message_id"] for inst in data["instructions"]}
    for msg in new_messages:
        if msg["message_id"] not in existing_ids:
            data["instructions"].append(msg)

    # 파일에 저장 (원자적 쓰기)
    _atomic_json_write(NEW_INSTRUCTIONS_FILE, data)

    print(f"💾 새 지시사항 저장: {len(new_messages)}개")


def load_new_instructions():
    """
    저장된 새 지시사항 읽기

    Returns:
        list: 새 지시사항 리스트
    """
    if not os.path.exists(NEW_INSTRUCTIONS_FILE):
        return []

    try:
        with open(NEW_INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("instructions", [])
    except Exception as e:
        print(f"⚠️ new_instructions.json 읽기 오류: {e}")
        return []


def clear_new_instructions():
    """
    새 지시사항 파일 삭제 (작업 완료 후 호출)
    """
    if os.path.exists(NEW_INSTRUCTIONS_FILE):
        try:
            os.remove(NEW_INSTRUCTIONS_FILE)
            print("🧹 새 지시사항 파일 정리 완료")
        except OSError as e:
            print(f"⚠️ new_instructions.json 삭제 오류: {e}")


def remove_working_lock():
    """작업 잠금 파일 삭제"""
    if os.path.exists(WORKING_LOCK_FILE):
        os.remove(WORKING_LOCK_FILE)
        print("🔓 작업 잠금 해제")


def load_index():
    """인덱스 파일 로드"""
    if not os.path.exists(INDEX_FILE):
        return {"tasks": [], "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ index.json 읽기 오류: {e}")
        return {"tasks": [], "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def save_index(index_data):
    """인덱스 파일 저장"""
    # tasks 폴더가 없으면 생성
    if not os.path.exists(TASKS_DIR):
        os.makedirs(TASKS_DIR)

    index_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _atomic_json_write(INDEX_FILE, index_data)


def _atomic_text_write(filepath: str, text: str) -> None:
    """원자적 텍스트 파일 쓰기."""
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, filepath)


def _generate_summary(instruction: str, result_summary: str) -> str:
    """지시사항+결과에서 1줄 요약 생성 (최대 80자). LLM 없이 규칙 기반."""
    import re as _re
    clean = _re.sub(r'\[요청\s*\d+\]\s*(\([^)]*\)\s*)?', '', instruction)
    clean = clean.split("---")[0].strip()
    clean = _re.sub(r'\(msg_\d+에 합산됨\)', '', clean).strip()
    if not clean:
        clean = instruction[:80]

    instr_part = clean[:45].strip()
    if len(clean) > 45:
        instr_part += "…"

    result_part = ""
    if result_summary and result_summary != "(작업 진행 중...)":
        result_lines = [
            l.strip() for l in result_summary.split("\n")
            if l.strip() and not l.strip().startswith(("━", "📋", "🤖", "**"))
        ]
        if result_lines:
            result_part = result_lines[0][:35]
            if len(result_lines[0]) > 35:
                result_part += "…"

    return f"{instr_part} → {result_part}" if result_part else instr_part


def _extract_topics(instruction: str, result_summary: str) -> list:
    """지시사항+결과에서 시맨틱 토픽 태그 추출 (최대 5개)."""
    combined = f"{instruction} {result_summary}".lower()

    _TOPIC_MAP = {
        "메일분석": ["메일", "이메일", "email", "받은메일"],
        "검토의견": ["검토의견", "shop", "승인", "리뷰"],
        "제작현황": ["제작현황", "납품", "센코어", "작업일보", "생산"],
        "보고서": ["보고서", "브리핑", "briefing", "일일", "주간"],
        "PPT": ["ppt", "발표", "슬라이드", "프레젠테이션"],
        "이슈": ["이슈", "issue", "대응", "긴급", "리스크"],
        "도면": ["도면", "drawing", "dxf", "cad", "설계"],
        "일정": ["일정", "공정", "납기", "리드타임", "schedule"],
        "데이터분석": ["분석", "데이터", "엑셀", "excel", "boq"],
        "카카오톡": ["카톡", "카카오", "kakao"],
        "업무현황": ["현황", "대시보드", "메트릭", "상태"],
    }

    matched = []
    for topic, triggers in _TOPIC_MAP.items():
        if any(t in combined for t in triggers):
            matched.append(topic)
        if len(matched) >= 5:
            break
    return matched


def update_index(message_id, instruction, result_summary="", files=None, chat_id=None, timestamp=None):
    """
    인덱스 업데이트 (작업 추가 또는 수정)

    Args:
        message_id: 메시지 ID
        instruction: 지시사항
        result_summary: 결과 요약
        files: 파일 리스트
        chat_id: 채팅 ID
        timestamp: 메시지 시각
    """
    index = load_index()

    # 키워드 추출
    if is_enabled("rag_search"):
        # W5: 조사 제거 + 스톱워드 필터링으로 향상된 키워드 추출
        from scripts.telegram.memory_search import tokenize_query
        keywords = tokenize_query(instruction, stopwords=_MEMORY_STOPWORDS)[:10]
    else:
        # 기존 동작 (간단한 방식: 단어 분리)
        keywords = []
        for word in instruction.split():
            if len(word) >= 2:  # 2글자 이상만
                keywords.append(word)
        keywords = list(set(keywords))[:10]  # 중복 제거, 최대 10개

    # 기존 작업 찾기
    existing_task = None
    for task in index["tasks"]:
        if task["message_id"] == message_id:
            existing_task = task
            break

    # 시맨틱 요약 + 토픽 생성
    summary = _generate_summary(instruction, result_summary)
    topics = _extract_topics(instruction, result_summary)

    task_data = {
        "message_id": message_id,
        "timestamp": timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "instruction": instruction,
        "keywords": keywords,
        "summary": summary,
        "topics": topics,
        "result_summary": result_summary,
        "files": files or [],
        "chat_id": chat_id,
        "task_dir": os.path.join(TASKS_DIR, f"msg_{message_id}")
    }

    if existing_task:
        # 기존 작업 업데이트
        existing_task.update(task_data)
    else:
        # 새 작업 추가
        index["tasks"].append(task_data)

    # message_id 역순 정렬 (최신순)
    index["tasks"].sort(key=lambda x: x["message_id"], reverse=True)

    save_index(index)
    print(f"📇 인덱스 업데이트: message_id={message_id}")


def search_memory(keyword=None, message_id=None):
    """
    인덱스에서 작업 검색

    Args:
        keyword: 검색할 키워드 (instruction, keywords에서 검색)
        message_id: 특정 메시지 ID

    Returns:
        list: 매칭된 작업 메타데이터
    """
    index = load_index()

    if message_id is not None:
        # 특정 message_id로 검색
        for task in index["tasks"]:
            if task["message_id"] == message_id:
                return [task]
        return []

    if keyword:
        # W5: rag_search ON → TF-weighted relevance scoring
        if is_enabled("rag_search"):
            from scripts.telegram.memory_search import tokenize_query, rank_tasks
            tokens = tokenize_query(keyword, stopwords=_MEMORY_STOPWORDS)
            if not tokens:
                return []
            ranked = rank_tasks(index["tasks"], tokens)
            return [t for t, _s in ranked]

        # ── 기존 동작 (flag OFF) ──
        matches = []
        keyword_lower = keyword.lower()

        for task in index["tasks"]:
            # instruction 또는 keywords에 포함되어 있으면 매칭
            if (keyword_lower in task["instruction"].lower() or
                any(keyword_lower in kw.lower() for kw in task["keywords"])):
                matches.append(task)

        return matches

    # 조건 없으면 전체 반환
    return index["tasks"]


def load_index_summaries(limit: int = 30) -> str:
    """전체 작업 인덱스의 요약을 경량 텍스트로 반환 (~500 tokens).

    Claude Code 프롬프트에 포함하여 전체 작업 이력을 빠르게 파악.

    Args:
        limit: 최대 항목 수 (기본 30)

    Returns:
        str: 작업 요약 텍스트 (한 줄당 약 15-20 토큰)
    """
    index = load_index()
    tasks = index.get("tasks", [])
    if not tasks:
        return "이전 작업 이력 없음."

    lines = ["=== 작업 이력 요약 ==="]
    for task in tasks[:limit]:
        msg_id = task["message_id"]
        summary = task.get("summary", "")
        topics = task.get("topics", [])

        if not summary:
            summary = _generate_summary(
                task.get("instruction", ""),
                task.get("result_summary", ""),
            )

        topic_str = f" [{','.join(topics)}]" if topics else ""
        files_str = f" 📎{len(task.get('files', []))}" if task.get("files") else ""
        lines.append(f"#{msg_id}{topic_str}: {summary}{files_str}")

    return "\n".join(lines)


def get_task_dir(message_id):
    """
    메시지 ID 기반 작업 폴더 경로 반환

    Args:
        message_id: 텔레그램 메시지 ID

    Returns:
        str: 작업 폴더 경로 (예: "tasks/msg_5/")
    """
    task_dir = os.path.join(TASKS_DIR, f"msg_{message_id}")

    # 폴더가 없으면 생성
    if not os.path.exists(task_dir):
        os.makedirs(task_dir)
        print(f"📁 작업 폴더 생성: {task_dir}")

    return task_dir


def get_24h_context(messages, current_message_id):
    """
    최근 24시간 대화 내역 생성 (사용자 + 봇 응답 모두 포함)

    Args:
        messages: 전체 메시지 리스트
        current_message_id: 현재 처리 중인 메시지 ID

    Returns:
        str: 24시간 대화 내역 텍스트
    """
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)

    context_lines = ["=== 최근 24시간 대화 내역 ===\n"]

    for msg in messages:
        # 현재 메시지까지만 포함
        if msg.get("type") == "user" and msg["message_id"] == current_message_id:
            break

        # 24시간 이내 메시지만 포함
        msg_time = datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S")
        if msg_time < cutoff_time:
            continue

        # 메시지 타입에 따라 포맷 다르게
        msg_type = msg.get("type", "user")  # 기본값 user (하위 호환)

        if msg_type == "user":
            # 사용자 메시지
            user_name = msg.get("first_name", "사용자")
            text = msg.get("text", "")

            # 파일 정보 추가
            files = msg.get("files", [])
            if files:
                file_info = f" [첨부: {len(files)}개 파일]"
            else:
                file_info = ""

            # 🆕 위치 정보 추가
            location = msg.get("location")
            if location:
                location_info = f" [위치: {location['latitude']}, {location['longitude']}]"
            else:
                location_info = ""

            context_lines.append(f"[{msg['timestamp']}] {user_name}: {text}{file_info}{location_info}")

        elif msg_type == "bot":
            # 봇 응답
            text = msg.get("text", "")

            # 긴 응답은 요약
            if len(text) > 150:
                text_preview = text[:150] + "..."
            else:
                text_preview = text

            # 파일 정보 추가
            files = msg.get("files", [])
            if files:
                file_info = f" [전송: {', '.join(files)}]"
            else:
                file_info = ""

            context_lines.append(f"[{msg['timestamp']}] 🤖 자비스: {text_preview}{file_info}")

    if len(context_lines) == 1:
        return "최근 24시간 이내 대화 내역이 없습니다."

    return "\n".join(context_lines)


def classify_message(text: str) -> str:
    """
    메시지 분류: Action / Decision / Reference / Trash

    Args:
        text: 메시지 텍스트

    Returns:
        str: "action" | "decision" | "reference" | "trash"
    """
    if not text or not text.strip():
        return "trash"

    t = text.strip()
    lower = t.lower()

    # Trash: 봇 명령어, 빈 메시지
    if lower in ("/start", "/start@", "/help", "/stop"):
        return "trash"

    # 사용자 피드백 오버라이드: "이거 무시해" → trash, "이건 실행해" → action
    if any(p in lower for p in ["무시해", "무시 해", "스킵", "패스"]):
        return "trash"
    if any(p in lower for p in ["이건 실행", "실행해줘", "이거 처리"]):
        return "action"

    # Decision: 질문형 (선택 요구)
    decision_markers = ["할까", "어때", "좋을까", "괜찮", "가능할까", "해볼까", "어떨까", "뭘까",
                        "할지", "어떻게", "선택", "추천", "어떤"]
    if any(m in t for m in decision_markers) or t.endswith("?"):
        return "decision"

    # Action: 명령형 (실행 요구)
    action_markers = ["해줘", "하세요", "해주세요", "실행", "생성", "분석", "보고",
                      "만들어", "정리", "확인", "동기화", "검색", "처리",
                      "브리핑", "트리아지", "점검", "루틴", "보내줘", "알려줘",
                      "수정", "삭제", "추가", "업데이트", "변경"]
    if any(m in t for m in action_markers):
        return "action"

    # Reference: 정보 공유
    reference_markers = ["FYI", "fyi", "참고", "공유", "링크", "http://", "https://",
                         "보내드", "전달", "첨부"]
    if any(m in t for m in reference_markers):
        return "reference"

    # 기본값: action (안전하게 처리 대상으로)
    return "action"


def _poll_telegram_once():
    """Telegram API에서 새 메시지를 한 번 가져와서 json 업데이트.
    Listener 데몬이 실행 중이면 중복 폴링 방지를 위해 스킵."""
    from .telegram_listener import is_listener_running
    if is_listener_running():
        return
    from .telegram_listener import fetch_new_messages
    try:
        run_async_safe(fetch_new_messages())
    except Exception as e:
        print(f"⚠️ 폴링 중 오류: {e}")


def _cleanup_old_messages():
    """30일 초과 처리된 메시지 정리. 24시간 이내는 컨텍스트용, 30일까지는 참조용 보관."""
    data = load_telegram_messages()
    messages = data.get("messages", [])

    cutoff = datetime.now() - timedelta(days=30)

    cleaned = [
        msg for msg in messages
        if not msg.get("processed", False)
        or datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S") > cutoff
    ]

    removed = len(messages) - len(cleaned)
    if removed > 0:
        data["messages"] = cleaned
        save_telegram_messages(data)
        print(f"🧹 30일 초과 메시지 {removed}개 정리 완료")


def check_telegram():
    """
    새로운 텔레그램 명령 확인

    Returns:
        list: 대기 중인 지시사항 리스트
        [
            {
                "instruction": str,      # 실행할 명령
                "message_id": int,       # 메시지 ID
                "chat_id": int,          # 채팅 ID
                "timestamp": str,        # 메시지 시각
                "context_24h": str,      # 최근 24시간 대화 내역
                "user_name": str,        # 사용자 이름
                "stale_resume": bool     # 스탈 작업 재개 여부
            },
            ...
        ]
    """
    # 작업 잠금 확인
    lock_info = check_working_lock()

    if lock_info:
        # 스탈 작업인 경우 - 재시작
        if lock_info.get("stale"):
            print("🔄 스탈 작업 재시작")

            # 텔레그램 알림 전송
            from .telegram_sender import send_message_sync
            message_ids = lock_info.get("message_id")
            if not isinstance(message_ids, list):
                message_ids = [message_ids]

            # 첫 번째 메시지의 chat_id 찾기
            data = load_telegram_messages()
            messages = data.get("messages", [])
            chat_id = None
            for msg in messages:
                if msg["message_id"] in message_ids:
                    chat_id = msg["chat_id"]
                    break

            if chat_id:
                alert_msg = (
                    "⚠️ **이전 작업이 중단되었습니다**\n\n"
                    f"지시사항: {lock_info.get('instruction_summary')}...\n"
                    f"시작 시각: {lock_info.get('started_at')}\n"
                    f"마지막 활동: {lock_info.get('last_activity')}\n\n"
                    "처음부터 다시 시작합니다."
                )
                send_message_sync(chat_id, alert_msg)

            # 잠금 파일 삭제
            try:
                os.remove(WORKING_LOCK_FILE)
                print("🔓 스탈 잠금 삭제 완료")
            except OSError:
                pass

            # 미처리 메시지 찾아서 재시작 플래그 추가
            pending = []
            for msg in messages:
                if msg["message_id"] in message_ids and not msg.get("processed", False):
                    instruction = msg.get("text", "")
                    message_id = msg["message_id"]
                    chat_id = msg["chat_id"]
                    timestamp = msg["timestamp"]
                    user_name = msg["first_name"]
                    files = msg.get("files", [])  # 🆕 파일 정보
                    location = msg.get("location")  # 🆕 위치 정보
                    context_24h = get_24h_context(messages, message_id)

                    pending.append({
                        "instruction": instruction,
                        "message_id": message_id,
                        "chat_id": chat_id,
                        "timestamp": timestamp,
                        "context_24h": context_24h,
                        "user_name": user_name,
                        "files": files,  # 🆕 파일 정보
                        "location": location,  # 🆕 위치 정보
                        "stale_resume": True  # 🆕 스탈 작업 재개 플래그
                    })

            return pending

        # 활동 중인 작업 - 대기
        print(f"⚠️ 다른 작업이 진행 중입니다: message_id={lock_info.get('message_id')}")
        print(f"   지시사항: {lock_info.get('instruction_summary')}")
        print(f"   시작 시각: {lock_info.get('started_at')}")
        print(f"   마지막 활동: {lock_info.get('last_activity')}")
        return []

    # Telegram API에서 새 메시지 수집 (Listener 별도 실행 불필요)
    _poll_telegram_once()

    # 30일 초과 처리된 메시지 정리 (24h 이내는 컨텍스트용, 30일까지 참조용 보관)
    _cleanup_old_messages()

    data = load_telegram_messages()
    messages = data.get("messages", [])

    pending = []

    for msg in messages:
        # 이미 처리된 메시지는 건너뛰기
        if msg.get("processed", False):
            continue

        # /start 명령 자동 처리 (pending에 포함하지 않음)
        raw_text = msg.get("text", "")
        if raw_text.strip().lower() in ("/start", "/start@"):
            try:
                from .telegram_sender import send_message_sync
                send_message_sync(
                    msg["chat_id"],
                    "P5 Agent Bot\n\n"
                    "텔레그램으로 지시사항을 보내면 자동으로 처리합니다.\n"
                    "예: `P5 이슈 분석해줘`, `브리핑 생성`, `전체점검`"
                )
            except Exception:
                pass
            # processed 마킹
            msg["processed"] = True
            msg["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_telegram_messages(data)
            continue

        # 새로운 명령 발견
        instruction = raw_text
        message_id = msg["message_id"]
        chat_id = msg["chat_id"]
        timestamp = msg["timestamp"]
        user_name = msg["first_name"]
        files = msg.get("files", [])  # 🆕 파일 정보
        location = msg.get("location")  # 🆕 위치 정보

        # 메시지 분류
        msg_class = classify_message(instruction)

        # 상태 전이: TRIAGED
        _update_message_state(message_id, MessageState.TRIAGED,
                              extra={"classification": msg_class})

        # Trash: 무시 (processed 마킹만)
        if msg_class == "trash":
            msg["processed"] = True
            msg["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            msg["classification"] = "trash"
            save_telegram_messages(data)
            continue

        # Reference: 메모리에만 저장
        if msg_class == "reference":
            msg["classification"] = "reference"
            # reference도 pending에 포함하되, classification 태그로 executor가 판단
            pass

        # 최근 24시간 대화 내역 생성
        context_24h = get_24h_context(messages, message_id)

        pending.append({
            "instruction": instruction,
            "message_id": message_id,
            "chat_id": chat_id,
            "timestamp": timestamp,
            "context_24h": context_24h,
            "user_name": user_name,
            "files": files,  # 🆕 파일 정보
            "location": location,  # 🆕 위치 정보
            "stale_resume": False,  # 일반 작업
            "classification": msg_class,  # action / decision / reference
        })

    return pending


def _format_file_size(size_bytes):
    """파일 크기를 사람이 읽기 쉬운 형식으로 변환"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.1f} MB"


def group_by_chat_id(pending_tasks):
    """
    Group pending tasks by chat_id to prevent cross-chat contamination.
    
    Args:
        pending_tasks: list of task dicts with 'chat_id' key
    
    Returns:
        dict: {chat_id: [tasks]}
    """
    groups = {}
    for task in pending_tasks:
        cid = task.get("chat_id", "unknown")
        groups.setdefault(cid, []).append(task)
    return groups


def combine_tasks(pending_tasks, include_24h_context=True):
    """
    여러 미처리 메시지를 하나의 통합 작업으로 합산

    Args:
        pending_tasks: check_telegram()이 반환한 작업 리스트
        include_24h_context: True면 24시간 대화 컨텍스트 포함 (Claude Code용),
                            False면 제외 (Python 직행 스킬용 — 토큰 절약)

    Returns:
        dict: {
            "combined_instruction": str,
            "message_ids": list,
            "chat_id": int,
            "timestamp": str,  # 첫 메시지 시각
            "user_name": str,
            "all_timestamps": list,  # 모든 메시지 시각
            "files": list,  # 🆕 모든 파일 정보
            "stale_resume": bool  # 스탈 작업 재개 여부
        }
    """
    if not pending_tasks:
        return None

    # chat_id isolation: only process tasks from the same chat
    groups = group_by_chat_id(pending_tasks)
    if len(groups) > 1:
        # Multiple chats have pending messages — pick the oldest chat first
        first_chat_id = min(
            groups.keys(),
            key=lambda cid: min(t['timestamp'] for t in groups[cid])
        )
        pending_tasks = groups[first_chat_id]
        remaining_count = sum(len(v) for k, v in groups.items() if k != first_chat_id)
        print(f"ℹ️ chat_id 격리: {first_chat_id} 처리 (나머지 {remaining_count}건은 다음 사이클)")

    # 시간순 정렬 (오래된 것부터)
    sorted_tasks = sorted(pending_tasks, key=lambda x: x['timestamp'])

    # 스탈 작업 재개 여부 확인
    is_stale_resume = any(task.get('stale_resume', False) for task in sorted_tasks)

    # 합산된 지시사항 생성
    combined_parts = []

    # 🆕 스탈 작업 재개인 경우 컨텍스트 추가
    if is_stale_resume:
        combined_parts.append("⚠️ [중단된 작업 재시작]")
        combined_parts.append("이전 작업의 진행 상태를 확인한 후, 합리적으로 진행할 것.")
        combined_parts.append("tasks/ 폴더에서 이전 작업 결과물을 확인하고, 이어서 작업할 수 있는 경우 이어서 진행하되,")
        combined_parts.append("처음부터 다시 시작하는 것이 더 안전하다면 처음부터 다시 시작할 것.")
        combined_parts.append("")
        combined_parts.append("---")
        combined_parts.append("")

    # 🆕 모든 파일 수집
    all_files = []

    for i, task in enumerate(sorted_tasks, 1):
        combined_parts.append(f"[요청 {i}] ({task['timestamp']})")

        # 텍스트가 있으면 추가
        if task['instruction']:
            combined_parts.append(task['instruction'])

        # 🆕 파일 정보 추가
        files = task.get('files', [])
        if files:
            combined_parts.append("")
            combined_parts.append("📎 첨부 파일:")
            for file_info in files:
                file_path = file_info['path']
                file_name = os.path.basename(file_path)
                file_type = file_info['type']
                file_size = _format_file_size(file_info.get('size', 0))

                # 파일 타입별 이모지
                type_emoji = {
                    'photo': '🖼️',
                    'document': '📄',
                    'video': '🎥',
                    'audio': '🎵',
                    'voice': '🎤'
                }
                emoji = type_emoji.get(file_type, '📎')

                combined_parts.append(f"  {emoji} {file_name} ({file_size})")
                combined_parts.append(f"     경로: {file_path}")

                # 전체 파일 리스트에 추가
                all_files.append(file_info)

        # 🆕 위치 정보 추가
        location = task.get('location')
        if location:
            combined_parts.append("")
            combined_parts.append("📍 위치 정보:")
            combined_parts.append(f"  위도: {location['latitude']}")
            combined_parts.append(f"  경도: {location['longitude']}")

            # 정확도 정보 (있으면)
            if 'accuracy' in location:
                combined_parts.append(f"  정확도: ±{location['accuracy']}m")

            # Google Maps 링크 생성
            maps_url = f"https://www.google.com/maps?q={location['latitude']},{location['longitude']}"
            combined_parts.append(f"  Google Maps: {maps_url}")

        combined_parts.append("")  # 빈 줄

    combined_instruction = "\n".join(combined_parts).strip()

    # 24시간 컨텍스트를 combined_instruction에 포함 (Claude가 직접 볼 수 있도록)
    context_24h = sorted_tasks[0]['context_24h']
    if include_24h_context and context_24h and context_24h != "최근 24시간 이내 대화 내역이 없습니다.":
        combined_instruction = combined_instruction + "\n\n---\n\n[참고사항]\n" + context_24h

    # 상태 전이: CONTEXT_READY (모든 메시지)
    for task in sorted_tasks:
        _update_message_state(task['message_id'], MessageState.CONTEXT_READY)

    return {
        "combined_instruction": combined_instruction,
        "message_ids": [task['message_id'] for task in sorted_tasks],
        "chat_id": sorted_tasks[0]['chat_id'],
        "timestamp": sorted_tasks[0]['timestamp'],
        "user_name": sorted_tasks[0]['user_name'],
        "all_timestamps": [task['timestamp'] for task in sorted_tasks],
        "context_24h": context_24h,
        "files": all_files,  # 🆕 모든 파일 정보
        "stale_resume": is_stale_resume  # 🆕 스탈 작업 재개 플래그
    }


def reserve_memory_telegram(instruction, chat_id, timestamp, message_id):
    """
    작업 시작 시 즉시 메모리 예약 (중복 방지)

    Args:
        instruction: 지시사항 (여러 메시지 합산 가능)
        chat_id: 채팅 ID
        timestamp: 메시지 시각 (또는 리스트)
        message_id: 메시지 ID (또는 리스트)
    """
    # message_id가 리스트인 경우 (여러 메시지 합산)
    if isinstance(message_id, list):
        message_ids = message_id
        main_message_id = message_ids[0]
        timestamps = timestamp if isinstance(timestamp, list) else [timestamp] * len(message_ids)
    else:
        message_ids = [message_id]
        main_message_id = message_id
        timestamps = [timestamp]

    # 메인 작업 폴더 생성 (첫 번째 메시지 ID)
    task_dir = get_task_dir(main_message_id)
    filepath = os.path.join(task_dir, "task_info.txt")

    now = datetime.now()

    # 메시지 ID 정보
    if len(message_ids) > 1:
        msg_id_info = f"{', '.join(map(str, message_ids))} (합산 {len(message_ids)}개)"
        msg_date_info = "\n".join([f"  - msg_{mid}: {ts}" for mid, ts in zip(message_ids, timestamps)])
    else:
        msg_id_info = str(main_message_id)
        msg_date_info = timestamps[0]

    # 메모리 파일 생성 (지시만 먼저 기록)
    content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id_info}
[출처] Telegram (chat_id: {chat_id})
[메시지날짜]
{msg_date_info}
[지시] {instruction}
[결과] (작업 진행 중...)
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    # 메인 메시지 인덱스 업데이트
    update_index(
        message_id=main_message_id,
        instruction=instruction,
        result_summary="(작업 진행 중...)",
        files=[],
        chat_id=chat_id,
        timestamp=timestamps[0]
    )

    # 추가 메시지들도 참조 파일 생성
    for i, (msg_id, ts) in enumerate(zip(message_ids[1:], timestamps[1:]), 2):
        ref_dir = get_task_dir(msg_id)
        ref_file = os.path.join(ref_dir, "task_info.txt")
        ref_content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id}
[출처] Telegram (chat_id: {chat_id})
[메시지날짜] {ts}
[지시] (메인 작업 msg_{main_message_id}에 합산됨)
[참조] tasks/msg_{main_message_id}/
[결과] (작업 진행 중...)
"""
        with open(ref_file, "w", encoding="utf-8") as f:
            f.write(ref_content)

        # 인덱스에도 추가
        update_index(
            message_id=msg_id,
            instruction=f"(msg_{main_message_id}에 합산됨)",
            result_summary="(작업 진행 중...)",
            files=[],
            chat_id=chat_id,
            timestamp=ts
        )

    print(f"📝 메모리 예약 완료: {task_dir}/task_info.txt")
    if len(message_ids) > 1:
        print(f"   합산 메시지: {len(message_ids)}개 ({', '.join(map(str, message_ids))})")


def report_telegram(instruction, result_text, chat_id, timestamp, message_id, files=None):
    """
    작업 결과를 텔레그램으로 전송하고 메모리에 저장

    Args:
        instruction: 원본 지시사항 (여러 메시지 합산 가능)
        result_text: 실행 결과
        chat_id: 채팅 ID
        timestamp: 메시지 시각 (또는 리스트)
        message_id: 메시지 ID (또는 리스트)
        files: 첨부 파일 리스트 (선택)
    """
    # message_id가 리스트인 경우 (여러 메시지 합산)
    if isinstance(message_id, list):
        message_ids = message_id
        main_message_id = message_ids[0]
        timestamps = timestamp if isinstance(timestamp, list) else [timestamp] * len(message_ids)
    else:
        message_ids = [message_id]
        main_message_id = message_id
        timestamps = [timestamp]

    # 결과 메시지 작성 (지시사항/참고사항 생략 - 텔레그램 대화창에 이미 있음)
    message = f"""🤖 **자비스 작업 완료**

**✅ 결과:**
{result_text}
"""

    if files:
        file_names = [os.path.basename(f) for f in files]
        message += f"\n**📎 첨부 파일:** {', '.join(file_names)}"

    if len(message_ids) > 1:
        message += f"\n\n_합산 처리: {len(message_ids)}개 메시지_"

    # 파일 경로 resolve (bare filename → task_dir 기준 절대경로)
    if files:
        task_dir = get_task_dir(main_message_id)
        resolved_files = []
        for f in files:
            if os.path.isabs(f) and os.path.exists(f):
                resolved_files.append(f)
            else:
                candidate = os.path.join(task_dir, f)
                if os.path.exists(candidate):
                    resolved_files.append(candidate)
                elif os.path.exists(f):
                    resolved_files.append(os.path.abspath(f))
                else:
                    print(f"⚠️ 파일 경로 resolve 실패: {f} (task_dir={task_dir})")
        files = resolved_files

    # 텔레그램으로 전송
    print(f"\n📤 텔레그램으로 결과 전송 중... (chat_id: {chat_id})")
    success = send_files_sync(chat_id, message, files or [])

    if success:
        print("✅ 결과 전송 완료!")
        # 상태 머신: COMPLETED
        _update_message_state(main_message_id, MessageState.COMPLETED)

        # 🆕 봇 응답을 telegram_messages.json에 저장 (대화 컨텍스트 유지)
        save_bot_response(
            chat_id=chat_id,
            text=message,
            reply_to_message_ids=message_ids,
            files=[os.path.basename(f) for f in (files or [])]
        )
    else:
        print("❌ 결과 전송 실패!")
        # 상태 머신: FAILED
        _update_message_state(
            main_message_id, MessageState.FAILED,
            extra={"reason": "send_files_sync failed"},
        )
        result_text = f"[전송 실패] {result_text}"
        files = []  # 파일 미전송이므로 보낸파일 비움

    # 메인 작업 폴더에 메모리 업데이트
    task_dir = get_task_dir(main_message_id)
    filepath = os.path.join(task_dir, "task_info.txt")

    now = datetime.now()

    # 메시지 ID 정보
    if len(message_ids) > 1:
        msg_id_info = f"{', '.join(map(str, message_ids))} (합산 {len(message_ids)}개)"
        msg_date_info = "\n".join([f"  - msg_{mid}: {ts}" for mid, ts in zip(message_ids, timestamps)])
    else:
        msg_id_info = str(main_message_id)
        msg_date_info = timestamps[0]

    # 메모리 내용 작성
    content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id_info}
[출처] Telegram (chat_id: {chat_id})
[메시지날짜]
{msg_date_info}
[지시] {instruction}
[결과] {result_text}
"""

    if files:
        file_names = [os.path.basename(f) for f in files]
        content += f"[보낸파일] {', '.join(file_names)}\n"

    # 메인 메모리 저장 (덮어쓰기)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    # 메인 메시지 인덱스 업데이트 (작업 완료 상태)
    update_index(
        message_id=main_message_id,
        instruction=instruction,
        result_summary=result_text[:100],  # 결과 요약 (최대 100자)
        files=[os.path.basename(f) for f in (files or [])],
        chat_id=chat_id,
        timestamp=timestamps[0]
    )

    # 프로젝트 컨텍스트 자동 갱신 (Strategy C)
    _update_project_context(
        instruction=instruction,
        result_summary=result_text[:200],
        files=[os.path.basename(f) for f in (files or [])],
        timestamp=timestamps[0],
        message_id=main_message_id,
    )

    # Obsidian 지식베이스에 워크로그 자동 저장
    obsidian_ok = _save_to_obsidian(
        instruction=instruction,
        result_text=result_text,
        files=files or [],
        timestamp=timestamps[0],
        message_id=main_message_id,
    )
    if not obsidian_ok:
        try:
            send_message_sync(chat_id,
                "⚠️ Obsidian 워크로그 저장에 실패했습니다. 작업 결과는 정상 전달되었습니다.")
        except Exception:
            pass

    # 추가 메시지들 참조 파일 업데이트
    for i, (msg_id, ts) in enumerate(zip(message_ids[1:], timestamps[1:]), 2):
        ref_dir = get_task_dir(msg_id)
        ref_file = os.path.join(ref_dir, "task_info.txt")
        ref_content = f"""[시간] {now.strftime("%Y-%m-%d %H:%M:%S")}
[메시지ID] {msg_id}
[출처] Telegram (chat_id: {chat_id})
[메시지날짜] {ts}
[지시] (메인 작업 msg_{main_message_id}에 합산됨)
[참조] tasks/msg_{main_message_id}/
[결과] {result_text[:100]}...
"""
        with open(ref_file, "w", encoding="utf-8") as f:
            f.write(ref_content)

        # 인덱스 업데이트
        update_index(
            message_id=msg_id,
            instruction=f"(msg_{main_message_id}에 합산됨)",
            result_summary=result_text[:100],
            files=[],
            chat_id=chat_id,
            timestamp=ts
        )

    print(f"💾 메모리 저장 완료: {task_dir}/task_info.txt")
    if len(message_ids) > 1:
        print(f"   합산 메시지: {len(message_ids)}개 처리 완료")

    return success


def mark_done_telegram(message_id):
    """
    텔레그램 메시지 처리 완료 표시

    Args:
        message_id: 메시지 ID (또는 리스트)
    """
    # message_id가 리스트인 경우 (여러 메시지 합산)
    if isinstance(message_id, list):
        message_ids = message_id
    else:
        message_ids = [message_id]

    # 🆕 작업 중에 추가된 새 지시사항도 함께 처리
    new_instructions = load_new_instructions()
    if new_instructions:
        print(f"📝 작업 중 추가된 지시사항 {len(new_instructions)}개 함께 처리")
        for inst in new_instructions:
            message_ids.append(inst["message_id"])

    data = load_telegram_messages()
    messages = data.get("messages", [])

    for msg in messages:
        if msg["message_id"] in message_ids:
            msg["processed"] = True

    save_telegram_messages(data)

    # 상태 머신: CLOSED
    for mid in message_ids:
        _update_message_state(mid, MessageState.CLOSED)

    # 🆕 새 지시사항 파일 정리
    clear_new_instructions()

    if len(message_ids) > 1:
        print(f"✅ 메시지 {len(message_ids)}개 처리 완료 표시: {', '.join(map(str, message_ids))}")
    else:
        print(f"✅ 메시지 {message_ids[0]} 처리 완료 표시")


def load_memory(limit=20, keywords=None, summary_only=False):
    """
    기존 메모리 파일 읽기 (tasks/*/task_info.txt)

    Args:
        limit: 최대 반환 개수 (기본 20건). 0 또는 None이면 전부 반환.
        keywords: 키워드 리스트. 있으면 인덱스 기반 필터링 (관련 메모리만 로드).
        summary_only: True면 디스크 읽기 없이 인덱스 메타데이터만 반환 (초경량).

    Returns:
        list: 메모리 내용 리스트 [{message_id, task_dir, content}, ...]
    """
    if not os.path.exists(TASKS_DIR):
        return []

    # ── 키워드 필터 모드: 인덱스 기반 빠른 매칭 ──
    if keywords:
        index = load_index()
        candidates = index.get("tasks", [])

        # W5: rag_search ON → TF-weighted relevance scoring
        if is_enabled("rag_search"):
            from scripts.telegram.memory_search import rank_tasks
            ranked = rank_tasks(candidates, keywords)
            filtered = [t for t, _s in ranked]
        else:
            # ── 기존 동작 (flag OFF) ──
            kw_set = {k.lower() for k in keywords}

            filtered = []
            for t in candidates:
                text_pool = (
                    t.get("instruction", "").lower() + " "
                    + " ".join(t.get("topics", [])).lower() + " "
                    + " ".join(t.get("keywords", [])).lower()
                )
                if any(kw in text_pool for kw in kw_set):
                    filtered.append(t)

        # rag_search ON → 이미 관련성순; OFF → message_id 역순
        if not is_enabled("rag_search"):
            filtered.sort(key=lambda x: x["message_id"], reverse=True)
        if limit and limit > 0:
            filtered = filtered[:limit]

        if summary_only:
            return [
                {
                    "message_id": t["message_id"],
                    "task_dir": t.get("task_dir", ""),
                    "content": f"[지시] {t['instruction'][:100]}\n[결과] {t.get('result_summary', '')[:150]}",
                }
                for t in filtered
            ]

        # 전체 내용 로드 (매칭된 것만)
        memories = []
        for t in filtered:
            td = t.get("task_dir", os.path.join(TASKS_DIR, f"msg_{t['message_id']}"))
            tf = os.path.join(td, "task_info.txt")
            if os.path.exists(tf):
                try:
                    with open(tf, "r", encoding="utf-8") as f:
                        memories.append({
                            "message_id": t["message_id"],
                            "task_dir": td,
                            "content": f.read(),
                        })
                except Exception:
                    pass
        return memories

    # ── 기존 동작 (필터 없음, 하위 호환) ──
    memories = []
    for task_folder in os.listdir(TASKS_DIR):
        if task_folder.startswith("msg_"):
            task_dir = os.path.join(TASKS_DIR, task_folder)
            task_info_file = os.path.join(task_dir, "task_info.txt")

            if os.path.exists(task_info_file):
                try:
                    message_id = int(task_folder.split("_")[1])
                    with open(task_info_file, "r", encoding="utf-8") as f:
                        content = f.read()
                        memories.append({
                            "message_id": message_id,
                            "task_dir": task_dir,
                            "content": content
                        })
                except Exception as e:
                    print(f"⚠️ {task_folder}/task_info.txt 읽기 오류: {e}")

    memories.sort(key=lambda x: x["message_id"], reverse=True)
    if limit is not None and limit > 0:
        memories = memories[:limit]
    return memories


# ── 스톱워드 (메모리 키워드 추출 시 필터링) ──
_MEMORY_STOPWORDS = {
    "해줘", "하세요", "해주세요", "합니다", "있는", "하는", "위해",
    "이거", "이것", "저것", "그거", "그것", "어떤", "어떻게", "그리고",
    "또는", "하고", "에서", "으로", "부터", "까지", "대한", "위한",
    "요청", "작업", "확인", "정리", "생성", "만들어", "좀", "것",
}


def load_memory_for_task(instruction: str, limit: int = 5) -> list:
    """지시사항에서 키워드를 추출하여 관련 메모리만 로드.

    Args:
        instruction: 현재 작업의 지시사항 텍스트
        limit: 최대 반환 개수 (기본 5)

    Returns:
        list: load_memory()와 동일 형식
    """
    # W5: rag_search ON → 조사 제거 + 스톱워드 필터링으로 향상된 키워드 추출
    if is_enabled("rag_search"):
        from scripts.telegram.memory_search import tokenize_query
        kws = tokenize_query(instruction, stopwords=_MEMORY_STOPWORDS)[:8]
    else:
        # ── 기존 동작 (flag OFF) ──
        words = instruction.replace("\n", " ").split()
        kws = []
        seen = set()
        for w in words:
            wl = w.lower().strip("[]()\"'.,!?")
            if len(wl) >= 2 and wl not in _MEMORY_STOPWORDS and wl not in seen:
                seen.add(wl)
                kws.append(wl)
            if len(kws) >= 8:
                break

    if not kws:
        return load_memory(limit=limit)

    results = load_memory(limit=limit, keywords=kws)

    # 결과가 너무 적으면 최근 작업으로 보충
    if len(results) < 2:
        recent = load_memory(limit=3)
        existing_ids = {r["message_id"] for r in results}
        for r in recent:
            if r["message_id"] not in existing_ids:
                results.append(r)
                if len(results) >= limit:
                    break

    return results


# ═══════════════════════════════════════════════════════════════
#  프로젝트 컨텍스트 자동 갱신 (Strategy C)
# ═══════════════════════════════════════════════════════════════

def _parse_project_context(text: str) -> dict:
    """기존 project_context.md를 파싱하여 dict로 반환.

    Returns:
        dict: {
            "recent_completions": [{"msg_id": int, "summary": str, "date": str}, ...],
            "contacts": set of str,
            "companies": set of str,
            "issue_codes": set of str,
            "custom_notes": str,
        }
    """
    import re as _re

    ctx = {
        "recent_completions": [],
        "contacts": set(),
        "companies": set(),
        "issue_codes": set(),
        "custom_notes": "",
    }

    if not text.strip():
        return ctx

    # --- 최근 완료 파싱 ---
    comp_block = _re.search(
        r"## 최근 완료 작업.*?\n((?:- .*\n)*)", text
    )
    if comp_block:
        for line in comp_block.group(1).strip().split("\n"):
            m = _re.match(r"- #(\d+)\s+\(([^)]+)\)\s*(.*)", line)
            if m:
                ctx["recent_completions"].append({
                    "msg_id": int(m.group(1)),
                    "date": m.group(2),
                    "summary": m.group(3).strip(),
                })

    # --- 연락처 파싱 ---
    contact_block = _re.search(
        r"## 주요 연락처.*?\n((?:- .*\n)*)", text
    )
    if contact_block:
        for line in contact_block.group(1).strip().split("\n"):
            name = line.lstrip("- ").strip()
            if name:
                ctx["contacts"].add(name)

    # --- 회사/조직 파싱 ---
    company_block = _re.search(
        r"## 관련 조직.*?\n((?:- .*\n)*)", text
    )
    if company_block:
        for line in company_block.group(1).strip().split("\n"):
            name = line.lstrip("- ").strip()
            if name:
                ctx["companies"].add(name)

    # --- 이슈 코드 파싱 ---
    issue_block = _re.search(
        r"## 이슈 코드.*?\n((?:- .*\n)*)", text
    )
    if issue_block:
        for line in issue_block.group(1).strip().split("\n"):
            code = line.lstrip("- ").strip()
            if code:
                ctx["issue_codes"].add(code)

    # --- 사용자 메모 파싱 ---
    notes_block = _re.search(
        r"## 메모\n(.*?)(?=\n## |\Z)", text, _re.DOTALL
    )
    if notes_block:
        ctx["custom_notes"] = notes_block.group(1).strip()

    return ctx


def _write_project_context(ctx: dict) -> None:
    """dict를 project_context.md 마크다운으로 원자적 기록."""
    lines = ["# P5 프로젝트 컨텍스트", ""]

    # 최근 완료 (최대 7개)
    lines.append("## 최근 완료 작업")
    for task in ctx.get("recent_completions", [])[:7]:
        lines.append(f"- #{task['msg_id']} ({task['date']}) {task['summary']}")
    lines.append("")

    # 연락처
    contacts = sorted(ctx.get("contacts", set()))
    if contacts:
        lines.append("## 주요 연락처")
        for c in contacts[:20]:
            lines.append(f"- {c}")
        lines.append("")

    # 조직
    companies = sorted(ctx.get("companies", set()))
    if companies:
        lines.append("## 관련 조직")
        for c in companies[:15]:
            lines.append(f"- {c}")
        lines.append("")

    # 이슈 코드
    issue_codes = sorted(ctx.get("issue_codes", set()))
    if issue_codes:
        lines.append("## 이슈 코드")
        for code in issue_codes[:30]:
            lines.append(f"- {code}")
        lines.append("")

    # 메모
    if ctx.get("custom_notes"):
        lines.append("## 메모")
        lines.append(ctx["custom_notes"])
        lines.append("")

    _atomic_text_write(PROJECT_CONTEXT_FILE, "\n".join(lines))


def _update_project_context(
    instruction: str,
    result_summary: str,
    files: list,
    timestamp: str,
    message_id: int,
) -> None:
    """report_telegram() 호출 시 project_context.md 자동 갱신.

    - 최근 완료 작업 추가 (최대 7개 유지)
    - 인물/조직/이슈 코드 자동 추출 & 누적
    """
    import re as _re

    # 기존 컨텍스트 로드
    existing_text = ""
    if os.path.exists(PROJECT_CONTEXT_FILE):
        try:
            with open(PROJECT_CONTEXT_FILE, "r", encoding="utf-8") as f:
                existing_text = f.read()
        except Exception:
            pass

    ctx = _parse_project_context(existing_text)

    # --- 1. 최근 완료 추가 ---
    summary = _generate_summary(instruction, result_summary)
    date_str = timestamp[:10] if isinstance(timestamp, str) and len(timestamp) >= 10 else datetime.now().strftime("%Y-%m-%d")

    # 동일 msg_id가 이미 있으면 교체
    ctx["recent_completions"] = [
        t for t in ctx["recent_completions"] if t["msg_id"] != message_id
    ]
    ctx["recent_completions"].insert(0, {
        "msg_id": message_id,
        "date": date_str,
        "summary": summary,
    })
    # 최대 7개 유지
    ctx["recent_completions"] = ctx["recent_completions"][:7]

    # --- 2. 엔티티 추출 ---
    combined = f"{instruction} {result_summary}"

    # 인물 (한글 이름 + 직함)
    _TITLE_PATTERN = _re.compile(
        r"([가-힣]{2,4})\s*(전무|상무|부장|차장|과장|대리|사원|소장|팀장|실장|센터장|이사|대표|사장|본부장|부본부장|위원|박사|교수|기사|기술사)"
    )
    for m in _TITLE_PATTERN.finditer(combined):
        ctx["contacts"].add(f"{m.group(1)} {m.group(2)}")

    # 조직/회사 (자주 등장하는 패턴)
    _COMPANY_PATTERN = _re.compile(
        r"([가-힣A-Za-z]{2,10})\s*(주식회사|건설|엔지니어링|설계|감리|시공사|E&C|이앤씨|컨설팅)"
    )
    for m in _COMPANY_PATTERN.finditer(combined):
        ctx["companies"].add(f"{m.group(1)} {m.group(2)}")

    # 이슈 코드 (SEN-001, RFI-002, NCR-003 등)
    _ISSUE_PATTERN = _re.compile(r"\b([A-Z]{2,5}-\d{2,5})\b")
    for m in _ISSUE_PATTERN.finditer(combined):
        ctx["issue_codes"].add(m.group(1))

    # --- 3. 기록 ---
    try:
        _write_project_context(ctx)
    except Exception as e:
        print(f"⚠️ project_context.md 갱신 실패: {e}")


def load_project_context() -> str:
    """프로젝트 컨텍스트 파일 로드.

    Returns:
        str: project_context.md 내용 (약 200-400 tokens). 없으면 빈 문자열.
    """
    if not os.path.exists(PROJECT_CONTEXT_FILE):
        return ""
    try:
        with open(PROJECT_CONTEXT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"⚠️ project_context.md 읽기 오류: {e}")
        return ""


def _save_to_obsidian(
    instruction: str,
    result_text: str,
    files: list,
    timestamp: str,
    message_id: int,
) -> bool:
    """작업 완료 시 Obsidian 지식베이스에 워크로그 노트 자동 저장.

    ResearchVault/P5-Project/05-WorkLog/ 에 날짜별 마크다운 파일 생성.
    """
    import re as _re

    try:
        os.makedirs(OBSIDIAN_WORKLOG_DIR, exist_ok=True)

        # 날짜/시간 파싱
        if isinstance(timestamp, str) and len(timestamp) >= 10:
            date_str = timestamp[:10]
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 지시사항에서 제목 추출 (첫 줄, 50자 이내)
        first_line = instruction.split("\n")[0].strip()
        # "[요청 N]" 패턴 제거
        first_line = _re.sub(r"\[요청\s*\d+\]\s*\([^)]*\)\s*", "", first_line).strip()
        if len(first_line) > 50:
            first_line = first_line[:50]
        # 파일명에 사용 불가한 문자 제거
        safe_title = _re.sub(r'[\\/*?:"<>|]', "", first_line).strip()
        if not safe_title:
            safe_title = f"작업_{message_id}"

        filename = f"{date_str}-msg{message_id}-{safe_title}.md"
        filepath = os.path.join(OBSIDIAN_WORKLOG_DIR, filename)

        # 태그 자동 추출
        tags = ["project/p5", "type/worklog"]
        tag_patterns = {
            "topic/mail": ["메일", "이메일", "email", "outlook"],
            "topic/issue": ["이슈", "issue", "SEN-"],
            "topic/fabrication": ["제작", "fabrication", "센코어"],
            "topic/drawing": ["도면", "drawing", "shop", "AFC"],
            "topic/briefing": ["브리핑", "briefing", "보고서"],
            "topic/kakao": ["카카오", "카톡", "kakao"],
            "topic/quantity": ["물량", "BOQ", "quantity"],
        }
        combined_text = f"{instruction} {result_text}".lower()
        for tag, keywords in tag_patterns.items():
            if any(kw.lower() in combined_text for kw in keywords):
                tags.append(tag)

        # 관련 이슈 코드 추출
        issue_codes = _re.findall(r"\b([A-Z]{2,5}-\d{2,5})\b", f"{instruction} {result_text}")
        issue_links = ""
        if issue_codes:
            unique_codes = list(dict.fromkeys(issue_codes))[:10]
            issue_links = "\n".join([f"- [[{code}]]" for code in unique_codes])

        # 결과 텍스트 정리 (최대 2000자)
        result_clean = result_text[:2000]
        if len(result_text) > 2000:
            result_clean += "\n\n_(결과 일부 생략)_"

        # 파일 목록
        files_section = ""
        if files:
            file_names = [os.path.basename(f) for f in files]
            files_section = "\n## 첨부 파일\n" + "\n".join([f"- `{fn}`" for fn in file_names])

        # Obsidian 노트 작성
        content = f"""---
title: "{safe_title}"
date: {date_str}
created: {now_str}
message_id: {message_id}
tags: [{", ".join(tags)}]
---

# {safe_title}

## 지시사항
{instruction}

## 결과
{result_clean}
{files_section}
"""
        if issue_links:
            content += f"\n## 관련 이슈\n{issue_links}\n"

        content += f"""
---
_Source: Telegram msg_{message_id} | {date_str}_
"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"📝 Obsidian 워크로그 저장: {filename}")
        return True

    except Exception as e:
        print(f"⚠️ Obsidian 워크로그 저장 실패: {e}")
        return False


# 테스트 코드
if __name__ == "__main__":
    print("=" * 60)
    print("텔레그램 봇 - 대기 중인 명령 확인")
    print("=" * 60)

    pending = check_telegram()

    if not pending:
        print("\n✅ 대기 중인 명령이 없습니다. 임무 완료!")
    else:
        print(f"\n📋 대기 중인 명령: {len(pending)}개\n")

        for i, task in enumerate(pending, 1):
            print(f"--- 명령 #{i} ---")
            print(f"메시지 ID: {task['message_id']}")
            print(f"사용자: {task['user_name']}")
            print(f"시각: {task['timestamp']}")
            print(f"명령: {task['instruction']}")
            print(f"\n[참고사항 - 최근 24시간 대화]")
            print(task['context_24h'])
            print()
