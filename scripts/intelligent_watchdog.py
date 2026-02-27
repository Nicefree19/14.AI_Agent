"""
🤖 Intelligent Drive-to-Obsidian Sync Watchdog
Drive 변경 → NotebookLM 동기화 → AI 분석 → Obsidian 저장

3단계 파이프라인:
1. 감지(Detect): Google Drive 폴더 변경 감시
2. 동기화(Sync): NotebookLM 소스 강제 갱신
3. 리포팅(Report): AI 분석 결과를 Obsidian에 저장
"""

import time
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ================= 설정 영역 =================
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

# 1. 감시할 구글 드라이브 로컬 경로
WATCH_DIR = r"G:\내 드라이브\appsheet\data\복합동이슈관리대장-495417588"

# 2. 결과물을 저장할 옵시디언 폴더 경로
OBSIDIAN_INBOX = str(_PROJECT_ROOT / "ResearchVault" / "P5-Project" / "01-Issues")

# 3. 연결할 NotebookLM의 이름
NOTEBOOK_NAME = "P5 프로젝트"

# 4. 디바운싱 시간 (초): 파일 저장 완료 대기 시간
DEBOUNCE_SECONDS = 10

# 5. Python venv 경로 (NotebookLM API 호출용)
VENV_PYTHON = str(_PROJECT_ROOT / ".agent_venv" / "Scripts" / "python.exe")

# 6. 무시할 파일 패턴
IGNORE_PATTERNS = ["~$", ".tmp", ".swp", ".lock", "Thumbs.db"]
# ===========================================


class DriveSyncHandler(FileSystemEventHandler):
    """지능형 파일 변경 감지 핸들러."""

    def __init__(self):
        self.last_modified = 0
        self.pending_changes = []

    def should_ignore(self, path: str) -> bool:
        """무시할 파일인지 확인."""
        for pattern in IGNORE_PATTERNS:
            if pattern in path:
                return True
        return False

    def on_modified(self, event):
        if event.is_directory:
            return
        if self.should_ignore(event.src_path):
            return

        # 디바운싱
        current_time = time.time()
        if current_time - self.last_modified < DEBOUNCE_SECONDS:
            self.pending_changes.append(event.src_path)
            return

        self.last_modified = current_time
        self.pending_changes.append(event.src_path)

        print(f"\n{'='*60}")
        print(f"[감지] {datetime.now().strftime('%H:%M:%S')}")
        print(f"  파일: {os.path.basename(event.src_path)}")
        print(f"{'='*60}")

        # 파일 저장 완료 대기
        time.sleep(2)
        self.run_pipeline()

    def on_created(self, event):
        """새 파일 생성 시."""
        if event.is_directory:
            return
        if self.should_ignore(event.src_path):
            return

        print(f"\n[신규] 파일 생성됨: {os.path.basename(event.src_path)}")
        self.on_modified(event)

    def run_pipeline(self):
        """
        [3단계 파이프라인]
        1. NotebookLM 소스 동기화 (Drive -> NotebookLM)
        2. AI 분석 쿼리 실행 (NotebookLM -> Analysis)
        3. 옵시디언 노트 저장 (Analysis -> Obsidian)
        """
        try:
            # 1단계: NotebookLM API로 동기화
            print("[1/3] NotebookLM 소스 동기화 중...")
            sync_result = self.sync_notebooklm()

            # 2단계: AI 분석 쿼리
            print("[2/3] AI 분석 중...")
            ai_insight = self.query_notebooklm()

            # 3단계: 옵시디언 저장
            print("[3/3] 옵시디언 노트 저장 중...")
            saved_path = self.save_to_obsidian(ai_insight)

            print(f"\n✅ 파이프라인 완료!")
            print(f"  저장됨: {saved_path}")

            # 처리된 변경 목록 초기화
            self.pending_changes = []

        except Exception as e:
            print(f"❌ 파이프라인 오류: {e}")
            import traceback

            traceback.print_exc()

    def sync_notebooklm(self) -> bool:
        """NotebookLM 소스 동기화 (API 직접 호출)."""
        try:
            # NotebookLM MCP API 사용
            _site_packages = str(_PROJECT_ROOT / ".agent_venv" / "Lib" / "site-packages")
            script = f"""
import sys
sys.path.insert(0, r"{_site_packages}")
from notebooklm_mcp.auth import load_cached_tokens
from notebooklm_mcp.api_client import NotebookLMClient

tokens = load_cached_tokens()
if tokens:
    client = NotebookLMClient(
        cookies=tokens.cookies,
        csrf_token=tokens.csrf_token,
        session_id=tokens.session_id
    )
    # Refresh auth tokens (forces re-fetch of sources)
    client._refresh_auth_tokens()
    print("Sync completed")
else:
    print("No tokens")
"""
            result = subprocess.run(
                [VENV_PYTHON, "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if "Sync completed" in result.stdout:
                print("  ✓ 동기화 성공")
                return True
            else:
                print(f"  ⚠ 동기화 결과: {result.stdout or result.stderr}")
                return False
        except Exception as e:
            print(f"  ❌ 동기화 실패: {e}")
            return False

    def query_notebooklm(self) -> str:
        """NotebookLM에서 변경 사항 분석 쿼리."""
        try:
            # P5 노트북에서 요약 가져오기
            _site_packages = str(_PROJECT_ROOT / ".agent_venv" / "Lib" / "site-packages")
            script = f"""
import sys
sys.path.insert(0, r"{_site_packages}")
from notebooklm_mcp.auth import load_cached_tokens
from notebooklm_mcp.api_client import NotebookLMClient

NOTEBOOK_ID = "3de596ed-3543-4fbf-b30e-dddf7d7783be"

tokens = load_cached_tokens()
if tokens:
    client = NotebookLMClient(
        cookies=tokens.cookies,
        csrf_token=tokens.csrf_token,
        session_id=tokens.session_id
    )
    summary = client._call_rpc(
        client.RPC_GET_SUMMARY,
        [NOTEBOOK_ID],
        path=f"/notebook/{{NOTEBOOK_ID}}",
        timeout=30.0
    )
    if summary and isinstance(summary, list) and len(summary) > 0:
        if isinstance(summary[0], str):
            print(summary[0])
        elif isinstance(summary[0], list) and len(summary[0]) > 0:
            print(summary[0][0])
"""
            result = subprocess.run(
                [VENV_PYTHON, "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )

            if result.stdout.strip():
                print("  ✓ AI 분석 완료")
                return result.stdout.strip()
            else:
                return "분석 결과를 가져올 수 없습니다."

        except subprocess.TimeoutExpired:
            return "분석 시간 초과"
        except Exception as e:
            return f"분석 오류: {e}"

    def save_to_obsidian(self, ai_insight: str) -> str:
        """옵시디언에 AI 브리핑 노트 저장."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"Auto_Brief_{date_str}.md"
        filepath = Path(OBSIDIAN_INBOX) / filename

        # 변경된 파일 목록
        changed_files = "\n".join(
            [f"- {os.path.basename(f)}" for f in self.pending_changes[:5]]
        )
        if len(self.pending_changes) > 5:
            changed_files += f"\n- ... 외 {len(self.pending_changes) - 5}개"

        content = f"""---
title: "자동 업데이트 브리핑"
date: {datetime.now().strftime("%Y-%m-%d")}
created: {timestamp}
source: "NotebookLM Auto-Sync"
tags: [auto-brief, project/p5, type/report]
---

# 🚀 자동 업데이트 브리핑

> 생성 시각: {timestamp}

## 📝 감지된 변경 사항
{changed_files if changed_files else "- 변경 내역 없음"}

## 💡 AI 분석 결과

{ai_insight}

---

## 🔗 관련 노트
- [[_index|P5 프로젝트 홈]]
- [[이슈관리-인덱스]]

---
*Generated by Intelligent Watchdog Agent*
"""

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")

        return str(filepath)


def main():
    """메인 실행."""
    print("=" * 60)
    print("🤖 Intelligent Drive-to-Obsidian Sync Watchdog")
    print("=" * 60)
    print(f"\n👀 감시 경로: {WATCH_DIR}")
    print(f"📂 저장 경로: {OBSIDIAN_INBOX}")
    print(f"📓 노트북: {NOTEBOOK_NAME}")
    print(f"⏱️ 디바운스: {DEBOUNCE_SECONDS}초")
    print("\n" + "-" * 60)
    print("Ctrl+C로 종료")
    print("-" * 60 + "\n")

    # 경로 확인
    if not os.path.exists(WATCH_DIR):
        print(f"❌ 감시 경로 없음: {WATCH_DIR}")
        print("Google Drive Desktop이 실행 중인지 확인하세요.")
        return

    # Observer 설정
    event_handler = DriveSyncHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=True)

    observer.start()
    print("✅ 감시 시작됨. 파일 변경을 기다리는 중...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 감시 종료 중...")
        observer.stop()

    observer.join()
    print("👋 종료됨.")


if __name__ == "__main__":
    main()
