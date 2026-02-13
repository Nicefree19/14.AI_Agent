"""
ResearchVault → NotebookLM 동기화 스크립트
watchdog로 .md 파일 변경 감지 후 NotebookLM MCP 서버에 동기화
"""

import os
import sys
import time
import logging
import threading
from pathlib import Path
from datetime import datetime

import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─── 설정 로드 ────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = Path(r"D:\00.Work_AI_Tool\14.AI_Agent\ResearchVault\_config\sync-config.yaml")

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "watch_path": r"D:\00.Work_AI_Tool\14.AI_Agent\ResearchVault",
        "file_patterns": ["*.md"],
        "ignore_patterns": [".obsidian/*", ".trash/*", "_config/*"],
        "debounce_seconds": 2,
        "max_retries": 3,
        "log_file": str(SCRIPT_DIR / "sync.log"),
    }

CFG = load_config()

# ─── 로깅 설정 ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(CFG["log_file"], encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("watchdog_sync")

# ─── 디바운서 ─────────────────────────────────────────────
class Debouncer:
    """파일별 디바운싱: 마지막 이벤트 후 N초 대기 후 콜백 실행"""

    def __init__(self, delay: float, callback):
        self.delay = delay
        self.callback = callback
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def trigger(self, filepath: str):
        with self._lock:
            if filepath in self._timers:
                self._timers[filepath].cancel()
            timer = threading.Timer(self.delay, self._fire, args=[filepath])
            self._timers[filepath] = timer
            timer.start()

    def _fire(self, filepath: str):
        with self._lock:
            self._timers.pop(filepath, None)
        self.callback(filepath)


# ─── 동기화 로직 ──────────────────────────────────────────
def should_ignore(filepath: str) -> bool:
    """무시 패턴 체크"""
    rel = os.path.relpath(filepath, CFG["watch_path"])
    for pattern in CFG["ignore_patterns"]:
        pattern_base = pattern.replace("/*", "").replace("\\*", "")
        if rel.startswith(pattern_base):
            return True
    return False


CHANGE_LOG_PATH = Path(CFG.get("watch_path", "")) / "P5-Project" / "00-Overview" / "vault-change-log.md"


def _append_change_log(rel_path: str, event_type: str, content_size: int):
    """변경 로그에 항목 추가 (하루 단위 섹션)"""
    try:
        CHANGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"- `{timestamp}` [{event_type}] `{rel_path}` ({content_size} chars)\n"

        if CHANGE_LOG_PATH.exists():
            existing = CHANGE_LOG_PATH.read_text(encoding="utf-8")
            # 오늘 날짜 섹션이 있으면 그 아래에 추가
            section_header = f"## {today}"
            if section_header in existing:
                existing = existing.replace(section_header + "\n", section_header + "\n" + entry, 1)
            else:
                existing += f"\n{section_header}\n{entry}"
            CHANGE_LOG_PATH.write_text(existing, encoding="utf-8")
        else:
            header = (
                "---\n"
                "title: Vault 변경 로그\n"
                "tags: [type/log, project/p5]\n"
                "---\n\n"
                "# Vault 변경 로그\n\n"
                "> watchdog_sync.py에 의해 자동 기록됩니다.\n\n"
            )
            CHANGE_LOG_PATH.write_text(header + f"## {today}\n{entry}", encoding="utf-8")
    except Exception as e:
        log.debug(f"변경 로그 기록 실패: {e}")


def _trigger_email_triage_if_needed(filepath: str):
    """00-Inbox/Messages/Emails 내 파일 변경 시 트리아지 자동 실행"""
    if "00-Inbox" in filepath and "Emails" in filepath and filepath.endswith(".md"):
        try:
            sys.path.insert(0, str(SCRIPT_DIR))
            from p5_email_triage import TriageRules, EmailParser, TriageEngine, apply_triage_results

            rules = TriageRules()
            parser = EmailParser(rules)
            engine = TriageEngine(rules)

            email = parser.parse_email_file(Path(filepath))
            if email:
                result = engine.triage(email)
                counts = apply_triage_results([(email, result)])
                log.info(
                    f"[자동트리아지] {Path(filepath).name}: "
                    f"score={result.total_score}, action={result.suggested_action}"
                )
        except ImportError:
            log.debug("[자동트리아지] p5_email_triage 모듈 미사용")
        except Exception as e:
            log.warning(f"[자동트리아지] 실패: {e}")


def sync_to_notebooklm(filepath: str):
    """파일 변경 감지 → 변경 로그 기록 + 자동 트리아지 (재시도 포함)"""
    rel = os.path.relpath(filepath, CFG["watch_path"])
    max_retries = CFG.get("max_retries", 3)

    for attempt in range(1, max_retries + 1):
        try:
            log.info(f"[동기화] {rel} (시도 {attempt}/{max_retries})")

            content = Path(filepath).read_text(encoding="utf-8")
            content_size = len(content)

            # 변경 로그에 기록
            _append_change_log(rel, "modified", content_size)

            # 이메일 파일이면 자동 트리아지
            _trigger_email_triage_if_needed(filepath)

            log.info(
                f"[완료] {rel} - {content_size} chars, "
                f"{datetime.now().strftime('%H:%M:%S')}"
            )
            return True

        except FileNotFoundError:
            log.warning(f"[삭제됨] {rel} — 파일이 삭제되어 동기화 건너뜀")
            _append_change_log(rel, "deleted", 0)
            return False
        except Exception as e:
            log.error(f"[오류] {rel} — {e}")
            if attempt < max_retries:
                wait = 2 ** attempt
                log.info(f"[재시도] {wait}초 후 재시도...")
                time.sleep(wait)
            else:
                log.error(f"[실패] {rel} — 최대 재시도 초과")
                return False


# ─── 이벤트 핸들러 ────────────────────────────────────────
class VaultHandler(FileSystemEventHandler):
    def __init__(self):
        self.debouncer = Debouncer(
            delay=CFG.get("debounce_seconds", 2),
            callback=sync_to_notebooklm,
        )

    def _handle(self, event):
        if event.is_directory:
            return
        filepath = event.src_path
        if not filepath.endswith(".md"):
            return
        if should_ignore(filepath):
            return
        log.debug(f"[이벤트] {event.event_type}: {filepath}")
        self.debouncer.trigger(filepath)

    def on_created(self, event):
        self._handle(event)

    def on_modified(self, event):
        self._handle(event)

    def on_moved(self, event):
        if event.dest_path.endswith(".md") and not should_ignore(event.dest_path):
            log.info(f"[이동] {event.src_path} → {event.dest_path}")
            self.debouncer.trigger(event.dest_path)


# ─── 메인 ────────────────────────────────────────────────
def main():
    watch_path = CFG["watch_path"]
    log.info(f"=== ResearchVault 감시 시작 ===")
    log.info(f"경로: {watch_path}")
    log.info(f"디바운스: {CFG.get('debounce_seconds', 2)}초")
    log.info(f"무시 패턴: {CFG['ignore_patterns']}")

    if not os.path.isdir(watch_path):
        log.error(f"감시 경로가 존재하지 않습니다: {watch_path}")
        sys.exit(1)

    handler = VaultHandler()
    observer = Observer()
    observer.schedule(handler, watch_path, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("=== 감시 종료 ===")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
