#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
회의/통화 내용 → 이슈 자동 연동 스킬 (Phase 7)

텔레그램으로 회의·통화 내용을 공유하면:
1. 음성이면 STT 변환 + 건설 도메인 오류 보정
2. 내용 구조화 (참석자, 결정사항, 액션아이템 추출)
3. 기존 이슈(SEN-xxx)에 3단계 매칭으로 자동 연결
4. 양방향 링크 (회의록→이슈 + 이슈→회의록)
5. 미매칭 항목은 새 이슈 생성 제안 (사용자 승인 후 생성)
6. Obsidian 회의록 노트 자동 저장
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── 경로 설정 ───────────────────────────────────────────────
_SKILLS_DIR = Path(__file__).resolve().parent           # scripts/telegram/skills/
_TELEGRAM_DIR = _SKILLS_DIR.parent                       # scripts/telegram/
_SCRIPTS_DIR = _TELEGRAM_DIR.parent                      # scripts/
_PROJECT_ROOT = _SCRIPTS_DIR.parent                      # 14.AI_Agent/
_VAULT_PATH = _PROJECT_ROOT / "ResearchVault"
_MEETINGS_DIR = _VAULT_PATH / "P5-Project" / "03-Meetings"
_ISSUES_DIR = _VAULT_PATH / "P5-Project" / "01-Issues"
_TELEGRAM_DATA = _PROJECT_ROOT / "telegram_data"
_PENDING_ISSUES_FILE = _TELEGRAM_DATA / "pending_issues.json"

# 오디오 확장자
_AUDIO_EXTENSIONS = {".ogg", ".opus", ".mp3", ".m4a", ".wav"}


# ═══════════════════════════════════════════════════════════════
#  메인 Executor: 회의록 이슈 연동
# ═══════════════════════════════════════════════════════════════

def run_meeting_transcript(context: dict) -> dict:
    """회의/통화 내용을 분석하여 이슈 자동 연동 및 회의록 생성.

    Executor 계약:
        입력: context (dict) — combined, memories, task_dir, send_progress
        출력: {"result_text": str, "files": list[str]}
    """
    from scripts.telegram.skill_utils import (
        detect_sen_refs,
        load_vault_issues,
        match_issues_by_topic,
        truncate_text,
        update_issue_field_append,
    )

    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")
    files_info = combined.get("files", [])
    task_dir = context.get("task_dir", "")

    try:
        # ── Step 1: 텍스트 확보 (텍스트 직접 / 음성 STT) ──
        send_progress("📝 [1/5] 회의 내용 확인 중...")
        transcript = ""
        input_type = "text"

        audio_files = _detect_audio_files(files_info)
        if audio_files:
            input_type = "voice"
            send_progress("🎙️ 음성 → 텍스트 변환 중 (Whisper)...")
            stt_results = []
            for af in audio_files:
                audio_path = af.get("local_path", "")
                if audio_path and os.path.isfile(audio_path):
                    stt_text = _run_stt(audio_path, task_dir)
                    stt_results.append(stt_text)
            if stt_results:
                raw_stt = "\n\n".join(stt_results)
                send_progress("🔧 STT 도메인 오류 보정 중...")
                transcript = _correct_stt_errors(raw_stt, task_dir)
            else:
                transcript = ""

        # 텍스트 모드: instruction에서 회의 내용 추출
        if not transcript:
            transcript = _extract_transcript_from_instruction(instruction)

        if not transcript or len(transcript.strip()) < 10:
            return {
                "result_text": (
                    "⚠️ 회의 내용이 충분하지 않습니다.\n\n"
                    "사용법:\n"
                    '• 텍스트: "회의록정리 오늘 구조검토. SEN-428 EP 확정..."\n'
                    "• 음성: 음성 메시지 + 회의록 키워드"
                ),
                "files": [],
            }

        # ── Step 2: Claude CLI로 구조화 추출 ──
        send_progress("🧠 [2/5] 회의 내용 구조화 중...")
        structured = _extract_meeting_structure(transcript, task_dir)

        if not structured:
            return {
                "result_text": "❌ 회의 내용 구조화에 실패했습니다.",
                "files": [],
            }

        # ── Step 3: 이슈 매칭 ──
        send_progress("🔗 [3/5] 이슈 매칭 중...")
        all_issues = load_vault_issues()
        matches, unmatched = _match_items_to_issues(structured, all_issues)

        # ── Step 4: 양방향 링크 업데이트 ──
        send_progress("📎 [4/5] 이슈 파일 업데이트 중...")
        meeting_date = structured.get("date", datetime.now().strftime("%Y-%m-%d"))
        meeting_title = structured.get("meeting_type", "회의")
        meeting_ref = f"MTG-{meeting_date}-{meeting_title}"
        updated_count = _update_matched_issues(matches, meeting_ref, meeting_date)

        # 새 이슈 제안 생성
        suggestions = _build_suggestions(unmatched)
        if suggestions:
            _save_pending_suggestions(suggestions, meeting_ref)

        # ── Step 5: Obsidian 회의록 저장 ──
        send_progress("📋 [5/5] Obsidian 회의록 저장 중...")
        meeting_file = _save_meeting_note(
            structured, matches, suggestions, input_type, task_dir,
        )

        # ── 텔레그램 요약 메시지 ──
        summary = _format_telegram_summary(
            structured, matches, suggestions, updated_count, meeting_file,
        )

        result_files = []
        if meeting_file and os.path.isfile(meeting_file):
            result_files.append(meeting_file)

        return {
            "result_text": truncate_text(summary),
            "files": result_files,
        }

    except Exception as e:
        return {
            "result_text": f"❌ 회의록 처리 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  이슈 승인 Executor
# ═══════════════════════════════════════════════════════════════

def run_meeting_issue_approval(context: dict) -> dict:
    """회의에서 제안된 새 이슈를 승인하여 생성.

    "이슈승인 1" 또는 "이슈승인 전체" 형식으로 호출.
    """
    from scripts.telegram.skill_utils import truncate_text

    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    instruction = combined.get("combined_instruction", "")

    try:
        # pending_issues.json 로드
        if not _PENDING_ISSUES_FILE.exists():
            return {
                "result_text": "📋 대기 중인 이슈 제안이 없습니다.",
                "files": [],
            }

        with open(_PENDING_ISSUES_FILE, "r", encoding="utf-8") as f:
            pending_data = json.load(f)

        # 만료 확인 (24시간)
        created_at = pending_data.get("created_at", "")
        if created_at:
            try:
                created_dt = datetime.fromisoformat(created_at)
                if datetime.now() - created_dt > timedelta(hours=24):
                    os.remove(_PENDING_ISSUES_FILE)
                    return {
                        "result_text": "⏰ 이슈 제안이 24시간 만료되었습니다. 회의록을 다시 처리해주세요.",
                        "files": [],
                    }
            except ValueError:
                pass

        suggestions = pending_data.get("suggestions", [])
        if not suggestions:
            return {
                "result_text": "📋 대기 중인 이슈 제안이 없습니다.",
                "files": [],
            }

        # 승인 대상 파싱
        text_lower = instruction.lower()
        approve_indices = []

        if "전체" in text_lower or "all" in text_lower:
            approve_indices = list(range(len(suggestions)))
        else:
            # 숫자 추출
            nums = re.findall(r"\d+", instruction)
            for n in nums:
                idx = int(n) - 1  # 1-based → 0-based
                if 0 <= idx < len(suggestions):
                    approve_indices.append(idx)

        if not approve_indices:
            lines = ["📋 대기 중인 이슈 제안:"]
            for i, s in enumerate(suggestions, 1):
                lines.append(f"  {i}. {s.get('title', '제목 없음')} ({s.get('category', '')})")
            lines.append('\n→ "이슈승인 1" 또는 "이슈승인 전체" 로 승인')
            return {"result_text": "\n".join(lines), "files": []}

        # 이슈 생성
        send_progress("🆕 이슈 생성 중...")
        created_issues = []

        for idx in approve_indices:
            suggestion = suggestions[idx]
            issue_id = _create_issue_from_suggestion(suggestion)
            if issue_id:
                created_issues.append(issue_id)

        # 생성 완료 후 pending 파일 정리
        remaining = [
            s for i, s in enumerate(suggestions)
            if i not in approve_indices
        ]
        if remaining:
            pending_data["suggestions"] = remaining
            _write_json_atomic(_PENDING_ISSUES_FILE, pending_data)
        else:
            os.remove(_PENDING_ISSUES_FILE)

        if created_issues:
            result = f"✅ {len(created_issues)}개 이슈 생성 완료:\n"
            result += "\n".join([f"  • {iid}" for iid in created_issues])
        else:
            result = "⚠️ 이슈 생성에 실패했습니다."

        return {"result_text": result, "files": []}

    except Exception as e:
        return {
            "result_text": f"❌ 이슈 승인 오류: {e}\n{traceback.format_exc()[-500:]}",
            "files": [],
        }


# ═══════════════════════════════════════════════════════════════
#  내부 함수: 오디오 감지 / STT
# ═══════════════════════════════════════════════════════════════

def _detect_audio_files(files_info: List[Dict]) -> List[Dict]:
    """첨부 파일에서 오디오 파일 필터링."""
    audio_files = []
    for f in (files_info or []):
        name = f.get("name", "")
        _, ext = os.path.splitext(name)
        if ext.lower() in _AUDIO_EXTENSIONS:
            audio_files.append(f)
        # Telegram voice message (mime type 기반)
        mime = f.get("mime_type", "")
        if "audio" in mime or "ogg" in mime:
            if f not in audio_files:
                audio_files.append(f)
    return audio_files


def _run_stt(audio_path: str, task_dir: str) -> str:
    """Whisper API STT 호출."""
    try:
        from scripts.telegram.skills.stt_utils import transcribe_audio
        return transcribe_audio(audio_path, language="ko")
    except Exception as e:
        return f"[STT 오류] {e}"


def _correct_stt_errors(raw_text: str, task_dir: str) -> str:
    """Claude CLI로 도메인 보정."""
    try:
        from scripts.telegram.skills.stt_utils import (
            build_correction_prompt,
            load_domain_dictionary,
        )

        domain_dict = load_domain_dictionary()
        prompt = build_correction_prompt(raw_text, domain_dict)

        claude_exe = _find_claude_cli()
        if not claude_exe:
            # CLI 없으면 간단한 규칙 기반 보정만
            return _apply_phonetic_correction(raw_text, domain_dict)

        result = subprocess.run(
            [str(claude_exe), "-p", "--dangerously-skip-permissions"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_PROJECT_ROOT),
            encoding="utf-8",
        )

        output = result.stdout.strip()
        if output and len(output) > 10:
            return output

        return raw_text

    except Exception:
        return raw_text


def _apply_phonetic_correction(text: str, domain_dict: Dict) -> str:
    """간단한 발음 매핑 기반 보정 (Claude CLI 없을 때 fallback)."""
    result = text
    phonetic = domain_dict.get("phonetic", {})
    for korean, english in phonetic.items():
        result = result.replace(korean, english)
    return result


# ═══════════════════════════════════════════════════════════════
#  내부 함수: 구조화 추출
# ═══════════════════════════════════════════════════════════════

def _extract_transcript_from_instruction(instruction: str) -> str:
    """instruction에서 회의록 키워드를 제거하고 회의 내용만 추출."""
    # 키워드 접두사 제거
    text = instruction
    prefixes = [
        "회의록정리", "회의록분석", "회의내용정리", "미팅노트", "미팅정리",
        "통화내용정리", "통화정리", "회의이슈연동", "회의결과정리",
        "회의이슈", "회의록", "회의내용", "통화내용",
    ]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    return text


def _extract_meeting_structure(transcript: str, task_dir: str) -> Optional[Dict]:
    """Claude CLI로 회의 내용 구조화 추출.

    Returns:
        {
            "date": str,
            "meeting_type": str,
            "attendees": [str],
            "decisions": [{"text": str, "issue_hint": str}],
            "action_items": [{"text": str, "assignee": str, "due": str}],
            "discussion_topics": [{"topic": str, "summary": str}],
            "unresolved": [str],
        }
    """
    prompt = f"""다음 회의/통화 내용을 분석하여 JSON으로 구조화해주세요.

[출력 형식 - 반드시 유효한 JSON만 출력]
{{
  "date": "YYYY-MM-DD (추정 또는 오늘 날짜)",
  "meeting_type": "회의 유형 (예: 구조검토회의, 설계협의, 공정회의)",
  "attendees": ["참석자1", "참석자2"],
  "decisions": [
    {{"text": "결정 내용", "issue_hint": "관련 이슈 ID 또는 키워드"}}
  ],
  "action_items": [
    {{"text": "할 일 내용", "assignee": "담당자", "due": "기한"}}
  ],
  "discussion_topics": [
    {{"topic": "논의 주제", "summary": "요약"}}
  ],
  "unresolved": ["미결사항1", "미결사항2"]
}}

[규칙]
1. SEN-xxx 이슈 ID가 언급되면 issue_hint에 포함
2. 날짜가 명시되지 않으면 오늘({datetime.now().strftime("%Y-%m-%d")}) 사용
3. JSON만 출력하고 다른 텍스트는 포함하지 마세요

[회의 내용]
{transcript}"""

    claude_exe = _find_claude_cli()
    if claude_exe:
        try:
            result = subprocess.run(
                [str(claude_exe), "-p", "--dangerously-skip-permissions"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=180,
                cwd=str(_PROJECT_ROOT),
                encoding="utf-8",
            )

            output = result.stdout.strip()
            return _parse_json_from_output(output)

        except Exception:
            pass

    # Claude CLI 없으면 간단한 규칙 기반 추출
    return _fallback_structure_extraction(transcript)


def _parse_json_from_output(output: str) -> Optional[Dict]:
    """Claude CLI 출력에서 JSON 추출."""
    if not output:
        return None

    # 직접 JSON 파싱 시도
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pass

    # ```json ... ``` 블록 추출
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # { ... } 블록 추출
    match = re.search(r"\{.*\}", output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _fallback_structure_extraction(transcript: str) -> Dict:
    """Claude CLI 없을 때 규칙 기반 구조 추출 (fallback)."""
    from scripts.telegram.skill_utils import detect_sen_refs

    today = datetime.now().strftime("%Y-%m-%d")
    sen_refs = detect_sen_refs(transcript)

    # 간단한 문장 분리
    sentences = re.split(r"[.。\n]+", transcript)
    sentences = [s.strip() for s in sentences if s.strip()]

    decisions = []
    action_items = []
    topics = []

    decision_keywords = ["확정", "결정", "승인", "합의", "진행"]
    action_keywords = ["수정", "검토", "확인", "보고", "준비", "제출", "완료"]

    for sent in sentences:
        sent_lower = sent.lower()

        # 결정사항 감지
        if any(kw in sent for kw in decision_keywords):
            hint = ""
            refs = detect_sen_refs(sent)
            if refs:
                hint = refs[0]
            decisions.append({"text": sent, "issue_hint": hint})

        # 액션 아이템 감지
        elif any(kw in sent for kw in action_keywords):
            action_items.append({
                "text": sent,
                "assignee": "",
                "due": "",
            })
        else:
            topics.append({"topic": sent[:30], "summary": sent})

    return {
        "date": today,
        "meeting_type": "회의",
        "attendees": [],
        "decisions": decisions,
        "action_items": action_items,
        "discussion_topics": topics[:5],
        "unresolved": [],
    }


# ═══════════════════════════════════════════════════════════════
#  내부 함수: 이슈 매칭 / 양방향 링크
# ═══════════════════════════════════════════════════════════════

def _match_items_to_issues(
    structured: Dict,
    all_issues: List[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """결정사항 + 액션아이템을 이슈에 3단계 매칭.

    Returns:
        (matched_list, unmatched_list)
        matched: [{"item": dict, "item_type": str, "match": match_result}]
        unmatched: [{"item": dict, "item_type": str}]
    """
    from scripts.telegram.skill_utils import match_issues_by_topic

    matched = []
    unmatched = []

    # 결정사항 매칭
    for decision in structured.get("decisions", []):
        text = decision.get("text", "")
        hint = decision.get("issue_hint", "")
        search_text = f"{hint} {text}" if hint else text

        results = match_issues_by_topic(search_text, all_issues, threshold=0.65, max_results=1)
        if results and results[0]["confidence"] >= 0.4:
            matched.append({
                "item": decision,
                "item_type": "decision",
                "match": results[0],
            })
        else:
            unmatched.append({"item": decision, "item_type": "decision"})

    # 액션아이템 매칭
    for action in structured.get("action_items", []):
        text = action.get("text", "")
        results = match_issues_by_topic(text, all_issues, threshold=0.65, max_results=1)
        if results and results[0]["confidence"] >= 0.4:
            matched.append({
                "item": action,
                "item_type": "action_item",
                "match": results[0],
            })
        else:
            unmatched.append({"item": action, "item_type": "action_item"})

    return matched, unmatched


def _update_matched_issues(
    matches: List[Dict],
    meeting_ref: str,
    meeting_date: str,
) -> int:
    """매칭된 이슈 파일에 양방향 링크 업데이트 (역방향: 이슈→회의록).

    Returns:
        업데이트된 이슈 수
    """
    from scripts.telegram.skill_utils import update_issue_field_append

    updated_ids = set()

    for m in matches:
        issue = m["match"]["issue"]
        issue_id = issue.get("issue_id", "")
        filepath = issue.get("_file_path", "")

        if not filepath or not os.path.isfile(filepath):
            # _file_path가 없으면 직접 탐색
            filepath = _find_issue_file(issue_id)
            if not filepath:
                continue

        if issue_id in updated_ids:
            continue

        # related_docs 에 회의록 참조 추가
        update_issue_field_append(filepath, "related_docs", meeting_ref)

        # 결정사항이면 decision 필드 업데이트
        if m["item_type"] == "decision":
            decision_text = m["item"].get("text", "")[:80]
            update_issue_field_append(
                filepath, "decision",
                f"{decision_text} (회의, {meeting_date})",
            )

        # 액션아이템이면 action_plan 필드 업데이트
        if m["item_type"] == "action_item":
            action_text = m["item"].get("text", "")[:80]
            assignee = m["item"].get("assignee", "")
            due = m["item"].get("due", "")
            suffix = ""
            if assignee:
                suffix += f" [{assignee}]"
            if due:
                suffix += f" (~{due})"
            update_issue_field_append(
                filepath, "action_plan",
                f"{action_text}{suffix} (회의, {meeting_date})",
            )

        updated_ids.add(issue_id)

    return len(updated_ids)


def _find_issue_file(issue_id: str) -> Optional[str]:
    """이슈 ID로 파일 경로 탐색."""
    if not _ISSUES_DIR.exists():
        return None

    # SEN-xxx.md 형태
    candidates = [
        _ISSUES_DIR / f"{issue_id}.md",
        _ISSUES_DIR / f"{issue_id.upper()}.md",
        _ISSUES_DIR / f"{issue_id.lower()}.md",
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    # 파일명에 이슈 ID 포함된 파일 검색
    id_upper = issue_id.upper()
    for f in _ISSUES_DIR.iterdir():
        if f.suffix == ".md" and id_upper in f.stem.upper():
            return str(f)

    return None


# ═══════════════════════════════════════════════════════════════
#  내부 함수: 새 이슈 제안
# ═══════════════════════════════════════════════════════════════

def _build_suggestions(unmatched: List[Dict]) -> List[Dict]:
    """미매칭 항목에서 새 이슈 제안 생성."""
    suggestions = []

    for item in unmatched:
        text = item["item"].get("text", "").strip()
        if not text or len(text) < 5:
            continue

        # 카테고리 추정
        category = _guess_category(text)

        suggestions.append({
            "title": text[:80],
            "category": category,
            "item_type": item["item_type"],
            "source_text": text,
        })

    return suggestions


def _guess_category(text: str) -> str:
    """텍스트에서 이슈 카테고리 추정."""
    text_lower = text.lower()
    category_keywords = {
        "psrc": ["psrc", "피에스알씨", "프리캐스트"],
        "hmb": ["hmb", "에이치엠비", "하이브리드"],
        "구조접합": ["접합", "임베디드", "앵커", "연결"],
        "설계": ["설계", "도면", "bim", "afc"],
        "간섭": ["간섭", "충돌", "클래시"],
        "pc연동": ["pc", "프리캐스트", "연동"],
        "일정": ["일정", "공정", "납기", "지연"],
    }

    for cat, keywords in category_keywords.items():
        if any(kw in text_lower for kw in keywords):
            return cat

    return "일반"


def _save_pending_suggestions(suggestions: List[Dict], meeting_ref: str) -> None:
    """새 이슈 제안을 pending_issues.json에 저장."""
    os.makedirs(_TELEGRAM_DATA, exist_ok=True)

    data = {
        "created_at": datetime.now().isoformat(),
        "meeting_ref": meeting_ref,
        "suggestions": suggestions,
    }

    _write_json_atomic(_PENDING_ISSUES_FILE, data)


def _create_issue_from_suggestion(suggestion: Dict) -> Optional[str]:
    """제안에서 이슈 파일 생성.

    Returns:
        생성된 이슈 ID 또는 None
    """
    title = suggestion.get("title", "새 이슈").replace('"', "'")
    category = suggestion.get("category", "일반").replace('"', "'")

    # 다음 SEN-ID 결정
    next_id = _get_next_sen_id()
    if not next_id:
        return None

    os.makedirs(_ISSUES_DIR, exist_ok=True)
    filepath = _ISSUES_DIR / f"{next_id}.md"

    today = datetime.now().strftime("%Y-%m-%d")
    content = f"""---
issue_id: "{next_id}"
title: "{title}"
category: "{category}"
priority: "medium"
status: "open"
owner: ""
created: "{today}"
source_origin: "meeting"
decision: ""
action_plan: ""
related_docs: ""
---

# {next_id}: {title}

## 설명
회의에서 도출된 이슈.

원문: {suggestion.get('source_text', '')}
"""

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return next_id
    except Exception:
        return None


def _get_next_sen_id() -> Optional[str]:
    """다음 SEN-xxx ID 결정."""
    if not _ISSUES_DIR.exists():
        return "SEN-001"

    max_num = 0
    for f in _ISSUES_DIR.iterdir():
        if f.suffix == ".md":
            match = re.search(r"SEN-(\d+)", f.stem, re.IGNORECASE)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

    return f"SEN-{max_num + 1:03d}"


# ═══════════════════════════════════════════════════════════════
#  내부 함수: Obsidian 회의록 저장
# ═══════════════════════════════════════════════════════════════

def _save_meeting_note(
    structured: Dict,
    matches: List[Dict],
    suggestions: List[Dict],
    input_type: str,
    task_dir: str,
) -> Optional[str]:
    """Obsidian 회의록 마크다운 생성.

    저장 위치: ResearchVault/P5-Project/03-Meetings/
    파일명: {date}-MTG-{safe_title}.md
    """
    os.makedirs(_MEETINGS_DIR, exist_ok=True)

    date_str = structured.get("date", datetime.now().strftime("%Y-%m-%d"))
    meeting_type = structured.get("meeting_type", "회의")
    attendees = structured.get("attendees", [])

    # 안전한 파일명 생성
    safe_title = re.sub(r'[\\/*?:"<>|]', "", meeting_type).strip()
    if not safe_title:
        safe_title = "회의"

    filename = f"{date_str}-MTG-{safe_title}.md"
    filepath = str(_MEETINGS_DIR / filename)

    # 중복 방지: 이미 존재하면 번호 추가
    counter = 1
    while os.path.exists(filepath):
        counter += 1
        filename = f"{date_str}-MTG-{safe_title}-{counter}.md"
        filepath = str(_MEETINGS_DIR / filename)

    # 관련 이슈 수집
    related_issue_ids = []
    for m in matches:
        iid = m["match"]["issue"].get("issue_id", "")
        if iid:
            related_issue_ids.append(iid)
    related_issue_ids = list(dict.fromkeys(related_issue_ids))

    # 태그 생성
    tags = ["project/p5", "type/meeting"]
    tag_topic_map = {
        "topic/psrc": ["psrc", "프리캐스트"],
        "topic/hmb": ["hmb"],
        "topic/structure": ["구조", "접합", "structural"],
        "topic/drawing": ["도면", "shop", "afc"],
        "topic/schedule": ["일정", "공정", "납기"],
    }
    combined_text = json.dumps(structured, ensure_ascii=False).lower()
    for tag, keywords in tag_topic_map.items():
        if any(kw in combined_text for kw in keywords):
            tags.append(tag)

    # 새 이슈 제안 제목
    suggestion_titles = [s.get("title", "") for s in suggestions]

    # YAML frontmatter — json.dumps로 안전한 직렬화
    attendees_yaml = json.dumps(attendees, ensure_ascii=False) if attendees else "[]"
    related_yaml = json.dumps(related_issue_ids, ensure_ascii=False) if related_issue_ids else "[]"
    suggestion_yaml = json.dumps(suggestion_titles, ensure_ascii=False) if suggestion_titles else "[]"
    tags_yaml = json.dumps(tags, ensure_ascii=False)

    # 본문 생성 — 제목에서 YAML 위험 문자 제거
    safe_meeting_type = meeting_type.replace('"', "'")

    lines = [
        "---",
        f'title: "{safe_meeting_type}"',
        f"date: {date_str}",
        f'meeting_type: "{safe_meeting_type}"',
        f"attendees: {attendees_yaml}",
        f'input_type: "{input_type}"',
        f"related_issues: {related_yaml}",
        f"new_issue_suggestions: {suggestion_yaml}",
        f"tags: {tags_yaml}",
        "---",
        "",
        f"# {meeting_type}",
        "",
    ]

    # 참석자
    if attendees:
        lines.append("## 참석자")
        for a in attendees:
            lines.append(f"- {a}")
        lines.append("")

    # 결정사항
    decisions = structured.get("decisions", [])
    if decisions:
        lines.append("## 결정사항")
        for i, d in enumerate(decisions, 1):
            text = d.get("text", "")
            hint = d.get("issue_hint", "")

            # 매칭된 이슈 위키링크 추가
            issue_link = ""
            for m in matches:
                if m["item_type"] == "decision" and m["item"].get("text") == text:
                    iid = m["match"]["issue"].get("issue_id", "")
                    if iid:
                        issue_link = f" **[[{iid}]]**:"
                    break

            if issue_link:
                lines.append(f"{i}.{issue_link} {text} ({date_str})")
            elif hint:
                lines.append(f"{i}. **{hint}**: {text}")
            else:
                lines.append(f"{i}. {text}")
        lines.append("")

    # 액션 아이템
    action_items = structured.get("action_items", [])
    if action_items:
        lines.append("## 액션 아이템")
        for a in action_items:
            text = a.get("text", "")
            assignee = a.get("assignee", "")
            due = a.get("due", "")
            prefix = f"{assignee}: " if assignee else ""
            suffix = f" (~{due})" if due else ""

            # 매칭된 이슈 확인
            issue_ref = ""
            for m in matches:
                if m["item_type"] == "action_item" and m["item"].get("text") == text:
                    iid = m["match"]["issue"].get("issue_id", "")
                    if iid:
                        issue_ref = f" → [[{iid}]]"
                    break

            lines.append(f"- [ ] {prefix}{text}{suffix}{issue_ref}")
        lines.append("")

    # 논의 주제
    topics = structured.get("discussion_topics", [])
    if topics:
        lines.append("## 논의 내용")
        for t in topics:
            topic = t.get("topic", "")
            summary = t.get("summary", "")
            if topic and summary:
                lines.append(f"### {topic}")
                lines.append(f"{summary}")
                lines.append("")
            elif summary:
                lines.append(f"- {summary}")
        lines.append("")

    # 미결사항
    unresolved = structured.get("unresolved", [])
    if unresolved:
        lines.append("## 미결사항")
        for u in unresolved:
            lines.append(f"- {u}")
        lines.append("")

    # 관련 이슈 섹션
    if related_issue_ids:
        lines.append("## 관련 이슈")
        for iid in related_issue_ids:
            lines.append(f"- [[{iid}]]")
        lines.append("")

    # 새 이슈 제안
    if suggestions:
        lines.append("## 새 이슈 제안 (미승인)")
        for s in suggestions:
            lines.append(f"- {s.get('title', '')} ({s.get('category', '')})")
        lines.append("")

    content = "\n".join(lines)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"📋 Obsidian 회의록 저장: {filename}")
        return filepath
    except Exception as e:
        print(f"⚠️ 회의록 저장 실패: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  내부 함수: 텔레그램 요약 포맷
# ═══════════════════════════════════════════════════════════════

def _format_telegram_summary(
    structured: Dict,
    matches: List[Dict],
    suggestions: List[Dict],
    updated_count: int,
    meeting_file: Optional[str],
) -> str:
    """텔레그램 응답용 요약 텍스트 생성."""
    lines = []

    meeting_type = structured.get("meeting_type", "회의")
    date_str = structured.get("date", "")
    lines.append(f"📋 **{meeting_type}** ({date_str})")
    lines.append("━" * 30)

    # 참석자
    attendees = structured.get("attendees", [])
    if attendees:
        lines.append(f"👥 참석: {', '.join(attendees)}")

    # 결정사항
    decisions = structured.get("decisions", [])
    if decisions:
        lines.append(f"\n📌 결정사항 ({len(decisions)}건)")
        for d in decisions[:5]:
            text = d.get("text", "")[:60]
            lines.append(f"  • {text}")

    # 액션 아이템
    action_items = structured.get("action_items", [])
    if action_items:
        lines.append(f"\n✅ 액션 아이템 ({len(action_items)}건)")
        for a in action_items[:5]:
            text = a.get("text", "")[:50]
            assignee = a.get("assignee", "")
            prefix = f"[{assignee}] " if assignee else ""
            lines.append(f"  • {prefix}{text}")

    # 이슈 매칭 결과
    if matches:
        lines.append(f"\n🔗 이슈 연동 ({len(matches)}건 매칭, {updated_count}건 업데이트)")
        for m in matches[:5]:
            issue = m["match"]["issue"]
            iid = issue.get("issue_id", "")
            title = issue.get("title", "")[:30]
            conf = m["match"]["confidence"]
            lines.append(f"  • {iid}: {title} ({conf:.0%})")

    # 미결사항
    unresolved = structured.get("unresolved", [])
    if unresolved:
        lines.append(f"\n⏳ 미결사항 ({len(unresolved)}건)")
        for u in unresolved[:3]:
            lines.append(f"  • {u[:50]}")

    # 새 이슈 제안
    if suggestions:
        lines.append(f"\n🆕 이슈 생성 제안:")
        for i, s in enumerate(suggestions, 1):
            title = s.get("title", "")[:50]
            cat = s.get("category", "")
            lines.append(f"  {i}. \"{title}\" ({cat})")
        lines.append('→ "이슈승인 1" 또는 "이슈승인 전체" 회신')

    # 저장 정보
    if meeting_file:
        fname = os.path.basename(meeting_file)
        lines.append(f"\n📁 Obsidian: P5-Project/03-Meetings/{fname}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════

def _find_claude_cli() -> Optional[str]:
    """Claude CLI 실행 파일 탐지."""
    import shutil

    user_local = os.path.join(
        os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe",
    )
    if os.path.exists(user_local):
        return user_local

    found = shutil.which("claude") or shutil.which("claude.cmd")
    if found:
        return found

    npm_global = os.path.join(
        os.environ.get("APPDATA", ""), "npm", "claude.cmd",
    )
    if os.path.exists(npm_global):
        return npm_global

    return None


def _write_json_atomic(filepath: Path, data: Any) -> None:
    """원자적 JSON 파일 쓰기."""
    tmp_path = str(filepath) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, str(filepath))
