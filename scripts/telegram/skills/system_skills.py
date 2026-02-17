#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
시스템 관리 스킬 모듈

스킬:
  - run_resend_failed: 전송실패 작업 자동 재전송
  - run_health_report: 시스템 헬스 리포트 생성
"""

from __future__ import annotations

import json
import os
import traceback
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from scripts.telegram.config import INDEX_FILE, TASKS_DIR, MESSAGES_FILE


def run_resend_failed(context: dict) -> dict:
    """전송실패된 작업 결과를 재전송.

    index.json에서 '[전송 실패]' 접두사가 있는 작업을 찾아
    원본 task_info.txt를 읽고 재전송을 시도한다.
    """
    send_progress = context.get("send_progress", lambda x: None)
    combined = context.get("combined", {})
    chat_id = combined.get("chat_id")

    send_progress("🔄 전송실패 작업 검색 중...")

    # index.json 읽기
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"result_text": "⚠️ 작업 인덱스를 읽을 수 없습니다.", "files": []}

    tasks = index_data.get("tasks", [])
    failed_tasks = [
        t for t in tasks
        if t.get("result_summary", "").startswith("[전송 실패]")
    ]

    if not failed_tasks:
        return {
            "result_text": "✅ 전송실패된 작업이 없습니다. 모든 작업이 정상 전달되었습니다.",
            "files": [],
        }

    send_progress(f"🔄 전송실패 {len(failed_tasks)}건 재전송 시도 중...")

    from scripts.telegram.telegram_sender import send_message_sync, send_files_sync

    success_count = 0
    fail_count = 0
    results = []

    for task in failed_tasks:
        msg_id = task.get("message_id")
        task_dir = task.get("task_dir", str(TASKS_DIR / f"msg_{msg_id}"))
        task_info_path = os.path.join(task_dir, "task_info.txt")

        # task_info.txt에서 결과 추출
        result_text = ""
        files_to_send = []

        if os.path.exists(task_info_path):
            try:
                with open(task_info_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # [결과] 섹션 파싱
                for line in content.split("\n"):
                    if line.startswith("[결과]"):
                        result_text = line[len("[결과]"):].strip()
                    elif line.startswith("[보낸파일]"):
                        file_names = line[len("[보낸파일]"):].strip()
                        if file_names:
                            for fname in file_names.split(","):
                                fname = fname.strip()
                                fpath = os.path.join(task_dir, fname)
                                if os.path.exists(fpath):
                                    files_to_send.append(fpath)
            except Exception:
                pass

        if not result_text:
            result_text = task.get("result_summary", "").replace("[전송 실패] ", "")

        if not result_text:
            fail_count += 1
            results.append(f"  ❌ msg_{msg_id}: 결과 데이터 없음")
            continue

        # 재전송 시도
        try:
            resend_text = f"🔄 **재전송** (msg\\_{msg_id})\n\n{result_text[:3500]}"
            target_chat = task.get("chat_id") or chat_id
            if not target_chat:
                fail_count += 1
                results.append(f"  ❌ msg_{msg_id}: chat_id 없음")
                continue

            if files_to_send:
                ok = send_files_sync(target_chat, resend_text, files_to_send)
            else:
                ok = send_message_sync(target_chat, resend_text)

            if ok:
                success_count += 1
                results.append(f"  ✅ msg_{msg_id}: 재전송 성공")
                # index에서 전송실패 접두사 제거
                task["result_summary"] = task["result_summary"].replace(
                    "[전송 실패] ", ""
                )
            else:
                fail_count += 1
                results.append(f"  ❌ msg_{msg_id}: 재전송 실패")
        except Exception as e:
            fail_count += 1
            results.append(f"  ❌ msg_{msg_id}: {e}")

    # 인덱스 업데이트 (성공한 건만)
    if success_count > 0:
        try:
            index_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tmp_path = str(INDEX_FILE) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(INDEX_FILE))
        except Exception as e:
            print(f"⚠️ 인덱스 업데이트 실패: {e}")

    detail = "\n".join(results)
    summary = (
        f"🔄 **전송실패 재전송 결과**\n\n"
        f"총 {len(failed_tasks)}건 중 ✅ {success_count}건 성공, "
        f"❌ {fail_count}건 실패\n\n{detail}"
    )
    return {"result_text": summary, "files": []}


def run_health_report(context: dict) -> dict:
    """시스템 헬스 리포트 생성.

    index.json 전체를 스캔하여 성공률, 실패율, 스킬별 사용량,
    평균 처리 빈도 등을 집계한다.
    """
    send_progress = context.get("send_progress", lambda x: None)
    send_progress("📊 시스템 헬스 데이터 수집 중...")

    # index.json 읽기
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"result_text": "⚠️ 작업 인덱스를 읽을 수 없습니다.", "files": []}

    tasks = index_data.get("tasks", [])
    if not tasks:
        return {"result_text": "⚠️ 작업 이력이 없습니다.", "files": []}

    # 기본 통계
    total = len(tasks)
    failed = sum(
        1 for t in tasks
        if t.get("result_summary", "").startswith("[전송 실패]")
    )
    in_progress = sum(
        1 for t in tasks
        if t.get("result_summary", "") == "(작업 진행 중...)"
    )
    success = total - failed - in_progress

    # 토픽별 분포
    topic_counter: Counter = Counter()
    for t in tasks:
        for topic in t.get("topics", []):
            topic_counter[topic] += 1

    # 날짜별 작업 수
    date_counter: Counter = Counter()
    for t in tasks:
        ts = t.get("timestamp", "")
        if ts:
            try:
                d = datetime.strptime(ts[:10], "%Y-%m-%d")
                date_counter[d.strftime("%m/%d")] += 1
            except (ValueError, IndexError):
                pass

    # 파일 전송 통계
    total_files = sum(len(t.get("files", [])) for t in tasks)

    # 최근 7일 활동
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    recent_tasks = []
    for t in tasks:
        ts = t.get("timestamp", "")
        if ts:
            try:
                dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                if dt >= week_ago:
                    recent_tasks.append(t)
            except (ValueError, IndexError):
                pass

    recent_count = len(recent_tasks)
    recent_failed = sum(
        1 for t in recent_tasks
        if t.get("result_summary", "").startswith("[전송 실패]")
    )

    # 리포트 구성
    lines = [
        "📊 **P5 자비스 시스템 헬스 리포트**",
        f"━{'━' * 28}",
        f"📅 기준: {now.strftime('%Y-%m-%d %H:%M')}",
        "",
        "**[전체 성과]**",
        f"  총 작업: {total}건",
        f"  ✅ 성공: {success}건 ({success/total*100:.0f}%)" if total else "  ✅ 성공: 0건",
        f"  ❌ 전송실패: {failed}건 ({failed/total*100:.0f}%)" if total else "  ❌ 전송실패: 0건",
        f"  🔄 진행중: {in_progress}건" if in_progress else "",
        f"  📎 전송 파일: {total_files}건",
        "",
        "**[최근 7일]**",
        f"  작업: {recent_count}건",
        f"  전송실패: {recent_failed}건",
        f"  성공률: {(recent_count-recent_failed)/recent_count*100:.0f}%" if recent_count else "  성공률: N/A",
        "",
    ]

    # 토픽 Top 5
    if topic_counter:
        lines.append("**[토픽별 분포 Top 5]**")
        for topic, count in topic_counter.most_common(5):
            bar = "█" * min(count, 20)
            lines.append(f"  {topic}: {count}건 {bar}")
        lines.append("")

    # 날짜별 활동 (최근 7일)
    if date_counter:
        lines.append("**[일별 작업량]**")
        sorted_dates = sorted(date_counter.items(), key=lambda x: x[0])[-7:]
        for date, count in sorted_dates:
            bar = "▓" * min(count, 15)
            lines.append(f"  {date}: {count}건 {bar}")
        lines.append("")

    # 개선 제안
    lines.append("**[시스템 상태]**")
    if failed > 0:
        lines.append(f"  ⚠️ 전송실패 {failed}건 → '재전송' 키워드로 복구 가능")
    if success / total >= 0.9 if total else False:
        lines.append("  ✅ 전체 성공률 90% 이상 — 양호")
    elif success / total >= 0.7 if total else False:
        lines.append("  🟡 전체 성공률 70-90% — 주의 필요")
    else:
        lines.append("  🔴 전체 성공률 70% 미만 — 점검 필요")

    # 필터링: 빈 줄 정리
    result_text = "\n".join(line for line in lines if line is not None)

    return {"result_text": result_text, "files": []}
