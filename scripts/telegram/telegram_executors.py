#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P5 프로젝트 작업 실행기 매핑 (Executor Dispatch)

텔레그램 지시 텍스트에서 키워드를 매칭하여 적절한 P5 작업 실행기를 반환한다.

Executor 계약:
    입력: context (dict) — combined, memories, task_dir, send_progress
    출력: {"result_text": str, "files": list[str]}
"""

from __future__ import annotations

import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# scripts/ 디렉토리를 import path에 추가
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


@dataclass
class ExecutorResult:
    """Executor 반환 데이터 클래스."""
    result_text: str
    files: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"result_text": self.result_text, "files": self.files}


# 키워드 → executor 이름 매핑 (순서 중요: 먼저 매칭되는 것이 우선)
KEYWORD_MAP = {
    # 일일 브리핑
    "briefing": "daily_briefing",
    "브리핑": "daily_briefing",
    "일일": "daily_briefing",
    # 이메일 트리아지
    "triage": "email_triage",
    "트리아지": "email_triage",
    "이메일": "email_triage",
    # OCR 파이프라인
    "ocr": "ocr_pipeline",
    "스캔": "ocr_pipeline",
    # 이슈 동기화
    "sync": "issue_sync",
    "동기화": "issue_sync",
    # 주간 보고서
    "report": "weekly_report",
    "보고서": "weekly_report",
    "주간": "weekly_report",
    # 메트릭스
    "metric": "metrics",
    "메트릭": "metrics",
    "현황": "metrics",
    # ── 복합 명령 (composite) ── (긴 키워드 먼저 배치)
    "아침루틴": "morning_routine",
    "morning": "morning_routine",
    "마감점검": "closing_check",
    "전체점검": "full_check",
    "아침": "morning_routine",
    "점검": "full_check",
    "마감": "closing_check",
}


def _run_briefing(context: dict) -> dict:
    """
    p5_daily_briefing.py 래핑 — 일일 브리핑 생성.
    """
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 일일 브리핑 생성 중...")

    try:
        from p5_daily_briefing import generate_briefing

        result = generate_briefing()
        result_text = result if isinstance(result, str) else str(result)

        return {"result_text": result_text, "files": []}

    except ImportError:
        return {
            "result_text": "⚠️ p5_daily_briefing 모듈을 찾을 수 없습니다.",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"❌ 브리핑 생성 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_triage(context: dict) -> dict:
    """
    p5_email_triage.py 래핑 — 이메일 트리아지 실행.
    """
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 이메일 트리아지 실행 중...")

    try:
        from p5_email_triage import EmailParser, load_config

        config = load_config()
        parser = EmailParser(config)
        results = parser.run_triage()

        if isinstance(results, dict):
            summary = results.get("summary", str(results))
            files = results.get("files", [])
        else:
            summary = str(results)
            files = []

        return {"result_text": summary, "files": files}

    except ImportError:
        return {
            "result_text": "⚠️ p5_email_triage 모듈을 찾을 수 없습니다.",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"❌ 트리아지 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_ocr(context: dict) -> dict:
    """
    p5_ocr_pipeline.py 래핑 — OCR 처리.
    """
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 OCR 파이프라인 실행 중...")

    try:
        from p5_ocr_pipeline import create_processor, create_ocr_client

        client = create_ocr_client()
        processor = create_processor(client)
        results = processor.process_pending()

        return {
            "result_text": f"OCR 처리 완료: {len(results)}건 처리됨",
            "files": [],
        }

    except ImportError:
        return {
            "result_text": "⚠️ p5_ocr_pipeline 모듈을 찾을 수 없습니다.",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"❌ OCR 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_sync(context: dict) -> dict:
    """
    p5_issue_sync.py 래핑 — 이슈 동기화.
    """
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 이슈 동기화 실행 중...")

    try:
        from p5_issue_sync import run_sync

        result = run_sync()
        result_text = result if isinstance(result, str) else str(result)

        return {"result_text": result_text, "files": []}

    except ImportError:
        return {
            "result_text": "⚠️ p5_issue_sync 모듈을 찾을 수 없습니다.",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"❌ 동기화 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _run_report(context: dict) -> dict:
    """
    주간 보고서 생성 — 메트릭 대시보드 + 주간 예외 보고서 통합.
    """
    send_progress = context.get("send_progress", lambda x: None)
    generated_files = []
    errors = []

    # ── 1단계: 운영 메트릭 대시보드 생성 ──
    send_progress("📊 [1/2] 운영 메트릭 생성 중...")
    try:
        from p5_metrics import cmd_generate as metrics_generate
        import argparse

        metrics_args = argparse.Namespace(stdout=False, command="generate")
        metrics_generate(metrics_args)

        metrics_path = Path(_SCRIPTS_DIR).parent / "ResearchVault" / "P5-Project" / "00-Overview" / "운영메트릭.md"
        if metrics_path.exists():
            generated_files.append(str(metrics_path))
    except Exception as e:
        errors.append(f"메트릭: {e}")

    # ── 2단계: 주간 예외 보고서 생성 ──
    send_progress("📊 [2/2] 주간 예외 보고서 생성 중...")
    try:
        from p5_email_triage import cmd_report as triage_report
        import argparse

        report_args = argparse.Namespace(command="report")
        triage_report(report_args)

        report_path = Path(_SCRIPTS_DIR).parent / "ResearchVault" / "P5-Project" / "00-Overview" / "주간예외보고서.md"
        if report_path.exists():
            generated_files.append(str(report_path))
    except Exception as e:
        errors.append(f"보고서: {e}")

    # ── 3단계: 요약 텍스트 구성 ──
    summary_parts = []

    # 메트릭 요약 읽기
    try:
        metrics_path = Path(_SCRIPTS_DIR).parent / "ResearchVault" / "P5-Project" / "00-Overview" / "운영메트릭.md"
        if metrics_path.exists():
            content = metrics_path.read_text(encoding="utf-8")
            # 핵심 지표 테이블 추출 (| 지표 | 상태 | 값 | 행들)
            table_lines = [
                line for line in content.split("\n")
                if line.startswith("| ") and "지표" not in line and "---" not in line
            ]
            if table_lines:
                summary_parts.append("📊 **운영 메트릭**")
                for line in table_lines[:6]:
                    # "| 이름 | 🟢 | 값 | 상세 |" → 간결하게 변환
                    cells = [c.strip() for c in line.split("|") if c.strip()]
                    if len(cells) >= 3:
                        summary_parts.append(f"  {cells[1]} {cells[0]}: {cells[2]}")
    except Exception:
        pass

    # 예외 보고서 요약 읽기
    try:
        report_path = Path(_SCRIPTS_DIR).parent / "ResearchVault" / "P5-Project" / "00-Overview" / "주간예외보고서.md"
        if report_path.exists():
            content = report_path.read_text(encoding="utf-8")
            # 액션 플랜 항목 추출
            action_lines = []
            in_action = False
            for line in content.split("\n"):
                if "액션 플랜" in line:
                    in_action = True
                    continue
                if in_action and line.startswith("##"):
                    break
                if in_action and line.strip().startswith(("1.", "2.", "3.", "4.", "5.")):
                    action_lines.append(line.strip())

            if action_lines:
                summary_parts.append("\n📋 **이번 주 액션 플랜**")
                for line in action_lines[:5]:
                    summary_parts.append(f"  {line}")

            # 데이터 품질 경고 추출
            warning_lines = []
            in_warning = False
            for line in content.split("\n"):
                if "데이터 품질 경고" in line:
                    in_warning = True
                    continue
                if in_warning and line.startswith("##"):
                    break
                if in_warning and line.strip().startswith("-"):
                    warning_lines.append(line.strip())

            if warning_lines:
                summary_parts.append("\n⚠️ **데이터 품질 경고**")
                for line in warning_lines[:5]:
                    summary_parts.append(f"  {line}")
    except Exception:
        pass

    # 최종 메시지 조합
    if summary_parts:
        result_text = "\n".join(summary_parts)
    else:
        result_text = "📊 주간 보고서가 생성되었습니다."

    if errors:
        result_text += f"\n\n⚠️ 일부 오류: {'; '.join(errors)}"

    if generated_files:
        result_text += f"\n\n📂 생성 파일: {len(generated_files)}개"

    return {"result_text": result_text, "files": generated_files}


def _run_morning_routine(context: dict) -> dict:
    """아침루틴 — 브리핑 + 메트릭 통합 조회."""
    send_progress = context.get("send_progress", lambda x: None)
    results = []
    files = []

    # 1. 일일 브리핑
    send_progress("☀️ [1/2] 일일 브리핑 생성 중...")
    try:
        r = _run_briefing(context)
        results.append(r.get("result_text", ""))
        files.extend(r.get("files", []))
    except Exception as e:
        results.append(f"❌ 브리핑 오류: {e}")

    # 2. 운영 메트릭
    send_progress("☀️ [2/2] 운영 메트릭 조회 중...")
    try:
        r = _run_metrics(context)
        results.append(r.get("result_text", ""))
        files.extend(r.get("files", []))
    except Exception as e:
        results.append(f"❌ 메트릭 오류: {e}")

    combined = "\n\n---\n\n".join(r for r in results if r)
    return {"result_text": f"☀️ **아침 루틴 완료**\n\n{combined}", "files": files}


def _run_full_check(context: dict) -> dict:
    """전체점검 — 모든 모듈 순차 실행."""
    send_progress = context.get("send_progress", lambda x: None)
    steps = [
        ("브리핑", _run_briefing),
        ("트리아지", _run_triage),
        ("동기화", _run_sync),
        ("메트릭", _run_metrics),
        ("보고서", _run_report),
    ]
    results = []
    files = []
    success = 0

    for i, (name, executor) in enumerate(steps, 1):
        send_progress(f"🔍 [{i}/{len(steps)}] {name} 실행 중...")
        try:
            r = executor(context)
            results.append(f"✅ **{name}**\n{r.get('result_text', '')[:500]}")
            files.extend(r.get("files", []))
            success += 1
        except Exception as e:
            results.append(f"❌ **{name}** 오류: {e}")

    header = f"🔍 **전체 점검 완료** ({success}/{len(steps)} 성공)\n"
    combined = "\n\n".join(results)
    return {"result_text": f"{header}\n{combined}", "files": files}


def _run_closing_check(context: dict) -> dict:
    """마감점검 — 트리아지 + 동기화 + 큐 건강도 요약."""
    send_progress = context.get("send_progress", lambda x: None)
    results = []
    files = []

    # 1. 트리아지
    send_progress("🌙 [1/3] 트리아지 실행 중...")
    try:
        r = _run_triage(context)
        results.append(r.get("result_text", ""))
        files.extend(r.get("files", []))
    except Exception as e:
        results.append(f"❌ 트리아지 오류: {e}")

    # 2. 동기화
    send_progress("🌙 [2/3] 이슈 동기화 중...")
    try:
        r = _run_sync(context)
        results.append(r.get("result_text", ""))
        files.extend(r.get("files", []))
    except Exception as e:
        results.append(f"❌ 동기화 오류: {e}")

    # 3. 큐 건강도 인라인 체크
    send_progress("🌙 [3/3] 큐 건강도 확인 중...")
    try:
        from p5_metrics import calc_queue_health
        qh = calc_queue_health()
        status_icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(qh.get("status", ""), "⚪")
        results.append(f"{status_icon} **큐 건강도**: {qh['value']} ({qh['detail']})")
    except Exception as e:
        results.append(f"⚠️ 큐 건강도 확인 실패: {e}")

    combined = "\n\n".join(r for r in results if r)
    return {"result_text": f"🌙 **마감 점검 완료**\n\n{combined}", "files": files}


def _run_metrics(context: dict) -> dict:
    """
    p5_metrics.py 래핑 — 메트릭 현황.
    """
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 메트릭 현황 조회 중...")

    try:
        from p5_metrics import generate_metrics_summary

        result = generate_metrics_summary()
        result_text = result if isinstance(result, str) else str(result)

        return {"result_text": result_text, "files": []}

    except ImportError:
        return {
            "result_text": "⚠️ p5_metrics 모듈을 찾을 수 없습니다.",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"❌ 메트릭 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _find_claude_cli() -> Optional[str]:
    """Claude CLI 실행 파일 탐지 (p5_autoexecutor.bat와 동일 탐색 순서).

    Returns:
        Claude CLI 경로 문자열, 또는 None.
    """
    import shutil

    # 1. User local bin (npm global install on Windows)
    user_local = os.path.join(
        os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe"
    )
    if os.path.exists(user_local):
        return user_local

    # 2. PATH 검색
    found = shutil.which("claude") or shutil.which("claude.cmd")
    if found:
        return found

    # 3. npm global directory
    npm_global = os.path.join(
        os.environ.get("APPDATA", ""), "npm", "claude.cmd"
    )
    if os.path.exists(npm_global):
        return npm_global

    return None


def _run_claude_cli(context: dict) -> dict:
    """키워드 미매칭 지시를 Claude CLI에 위임.

    Args:
        context: 표준 executor context (combined, memories, task_dir, send_progress)

    Returns:
        {"result_text": str, "files": list[str]}
    """
    import subprocess

    send_progress = context.get("send_progress", lambda x: None)
    combined = context["combined"]
    instruction = combined["combined_instruction"]
    task_dir = context.get("task_dir", "")

    send_progress("Claude CLI로 작업을 처리합니다...")

    claude_exe = _find_claude_cli()
    if not claude_exe:
        return {
            "result_text": (
                "Claude CLI를 찾을 수 없습니다.\n\n"
                "설치: npm install -g @anthropic-ai/claude-code"
            ),
            "files": [],
        }

    # 시스템 프롬프트 파일
    project_root = Path(__file__).resolve().parent.parent.parent
    spf = project_root / "scripts" / "CLAUDE_TELEGRAM.md"
    if not spf.exists():
        spf = project_root / "CLAUDE.md"

    prompt = (
        f"Process this Telegram task. The user sent:\n\n"
        f"{instruction}\n\n"
        f"Working directory: {task_dir}\n"
        f"Report results concisely in Korean."
    )

    cmd = [str(claude_exe), "-p", "--dangerously-skip-permissions"]
    if spf.exists():
        cmd.extend(["--append-system-prompt-file", str(spf)])

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(task_dir) if task_dir and Path(task_dir).is_dir() else str(project_root),
            encoding="utf-8",
        )

        output = result.stdout.strip()
        if result.returncode != 0 and not output:
            output = f"Claude CLI 실행 오류 (exit code {result.returncode})"
            if result.stderr:
                output += f"\n{result.stderr[:500]}"

        if not output:
            output = "작업이 완료되었으나 출력이 없습니다."

        # task_dir 내 생성된 파일 수집
        generated_files = []
        if task_dir and os.path.isdir(task_dir):
            for fname in os.listdir(task_dir):
                fpath = os.path.join(task_dir, fname)
                if os.path.isfile(fpath) and fname != "task_info.txt":
                    generated_files.append(fpath)

        return {
            "result_text": output[:4000],
            "files": generated_files,
        }

    except subprocess.TimeoutExpired:
        return {
            "result_text": "Claude CLI 실행 시간 초과 (10분).",
            "files": [],
        }
    except Exception as e:
        return {
            "result_text": f"Claude CLI 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


def _reference_executor(context: dict) -> dict:
    """
    Reference 분류 메시지 → 메모리에 저장 + 간단 확인 응답.
    """
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    snippet = instruction[:200] if instruction else "(내용 없음)"

    return {
        "result_text": (
            f"📌 참고 정보로 저장했습니다.\n\n"
            f"{snippet}\n\n"
            f"필요할 때 `메모리 조회`로 다시 확인할 수 있습니다."
        ),
        "files": [],
    }


def _decision_executor(context: dict) -> dict:
    """
    Decision 분류 메시지 → 판단/선택지 분석 후 응답.
    Claude CLI가 있으면 위임, 없으면 기본 응답.
    """
    # Claude CLI가 있으면 자연어 분석 위임 (더 스마트한 답변)
    if _find_claude_cli() is not None:
        return _run_claude_cli(context)

    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")[:200]

    return {
        "result_text": (
            f"🤔 질문을 확인했습니다.\n\n"
            f"\"{instruction}\"\n\n"
            f"Claude CLI가 설치되지 않아 자동 분석이 어렵습니다.\n"
            f"구체적인 명령어로 다시 보내주세요.\n"
            f"예: `브리핑 생성`, `이슈 동기화`, `전체점검`"
        ),
        "files": [],
    }


def _default_executor(context: dict) -> dict:
    """
    미매칭 명령 → 지원 명령 안내 메시지 반환.
    """
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")[:100]

    return {
        "result_text": (
            f"🤖 명령을 인식하지 못했습니다.\n\n"
            f"수신: \"{instruction}...\"\n\n"
            f"**지원하는 명령어:**\n"
            f"• `브리핑` / `briefing` — 일일 브리핑 생성\n"
            f"• `트리아지` / `triage` — 이메일 분류\n"
            f"• `스캔` / `ocr` — OCR 처리\n"
            f"• `동기화` / `sync` — 이슈 동기화\n"
            f"• `보고서` / `report` — 주간 보고서\n"
            f"• `현황` / `metric` — 메트릭 현황\n"
            f"\n**복합 명령어:**\n"
            f"• `아침루틴` / `morning` — 아침 브리핑+메트릭\n"
            f"• `전체점검` — 전체 시스템 점검\n"
            f"• `마감점검` / `마감` — 마감 트리아지+동기화+큐\n"
        ),
        "files": [],
    }


# Executor 레지스트리
EXECUTOR_MAP: Dict[str, Callable[[dict], dict]] = {
    "daily_briefing": _run_briefing,
    "email_triage": _run_triage,
    "ocr_pipeline": _run_ocr,
    "issue_sync": _run_sync,
    "weekly_report": _run_report,
    "metrics": _run_metrics,
    # 복합 명령
    "morning_routine": _run_morning_routine,
    "full_check": _run_full_check,
    "closing_check": _run_closing_check,
    # 분류 기반 executor
    "reference": _reference_executor,
    "decision": _decision_executor,
}


def get_executor(
    instruction_text: str,
    classification: str = "action",
) -> Callable[[dict], dict]:
    """
    메시지 분류 + 키워드 매칭으로 적절한 executor 반환.

    Args:
        instruction_text: 텔레그램에서 수신한 지시 텍스트
        classification: 메시지 분류 ("action", "decision", "reference", "trash")

    Returns:
        executor 함수 (context → {"result_text": str, "files": list})
    """
    # 분류별 라우팅 — action이 아닌 경우 전용 executor 우선
    if classification == "reference":
        return _reference_executor
    if classification == "decision":
        return _decision_executor

    # Action (기본): 키워드 매칭으로 executor 선택
    text_lower = instruction_text.lower()
    for keyword, executor_name in KEYWORD_MAP.items():
        if keyword in text_lower:
            executor = EXECUTOR_MAP.get(executor_name)
            if executor:
                return executor
    # 키워드 미매칭 → Claude CLI 설치 시 위임, 아니면 안내 메시지
    if _find_claude_cli() is not None:
        return _run_claude_cli
    return _default_executor


def list_executors() -> List[str]:
    """등록된 executor 이름 목록 반환."""
    return list(EXECUTOR_MAP.keys())
