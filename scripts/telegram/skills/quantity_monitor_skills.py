#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
물량 변동 감시 스킬 모듈

스킬:
  - run_quantity_monitor: 현재 물량 vs 기준 스냅샷 비교 → 변동률 보고
"""

from __future__ import annotations

import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from scripts.telegram.config import PROJECT_ROOT

# 물량 데이터 파일 경로
QUANTITY_DATA_FILE = PROJECT_ROOT / "ResearchVault" / "_config" / "p5-quantity-data.yaml"
SNAPSHOT_DIR = PROJECT_ROOT / "telegram_data" / "quantity_snapshots"

# 변동 알림 임계값 (%)
CHANGE_THRESHOLD = 5.0


def _load_quantity_data() -> dict:
    """p5-quantity-data.yaml 읽기."""
    if not QUANTITY_DATA_FILE.exists():
        return {}
    try:
        with open(QUANTITY_DATA_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_latest_snapshot() -> Optional[dict]:
    """가장 최근 스냅샷 로드."""
    if not SNAPSHOT_DIR.exists():
        return None

    snapshots = sorted(SNAPSHOT_DIR.glob("snapshot_*.yaml"), reverse=True)
    if not snapshots:
        return None

    try:
        with open(snapshots[0], "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _save_snapshot(data: dict) -> str:
    """현재 데이터를 스냅샷으로 저장 (원자적 쓰기)."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    filename = f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}.yaml"
    path = SNAPSHOT_DIR / filename
    tmp_path = str(path) + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, str(path))

    return str(path)


def _flatten_quantities(data: dict, prefix: str = "") -> Dict[str, float]:
    """중첩 YAML을 flat dict로 변환. 숫자 값만 추출."""
    result = {}
    for key, val in data.items():
        full_key = f"{prefix}/{key}" if prefix else key
        if isinstance(val, (int, float)):
            result[full_key] = float(val)
        elif isinstance(val, dict):
            result.update(_flatten_quantities(val, full_key))
    return result


def _calc_changes(
    current: Dict[str, float],
    previous: Dict[str, float],
) -> List[Dict[str, Any]]:
    """현재 vs 이전 비교 → 변동 리스트."""
    changes = []
    all_keys = set(current.keys()) | set(previous.keys())

    for key in sorted(all_keys):
        cur_val = current.get(key)
        prev_val = previous.get(key)

        if cur_val is not None and prev_val is not None and prev_val != 0:
            change_pct = (cur_val - prev_val) / abs(prev_val) * 100
            changes.append({
                "key": key,
                "current": cur_val,
                "previous": prev_val,
                "change_pct": change_pct,
                "abs_change": cur_val - prev_val,
            })
        elif cur_val is not None and prev_val is None:
            changes.append({
                "key": key,
                "current": cur_val,
                "previous": None,
                "change_pct": None,
                "abs_change": None,
                "note": "신규 항목",
            })
        elif cur_val is None and prev_val is not None:
            changes.append({
                "key": key,
                "current": None,
                "previous": prev_val,
                "change_pct": None,
                "abs_change": None,
                "note": "삭제된 항목",
            })

    return changes


def run_quantity_monitor(context: dict) -> dict:
    """선제작 물량 변동 감시.

    1. p5-quantity-data.yaml 읽기
    2. 최신 스냅샷과 비교
    3. 변동률 보고 (임계값 초과 항목 강조)
    4. 현재 데이터를 새 스냅샷으로 저장
    """
    send_progress = context.get("send_progress", lambda x: None)
    task_dir = context.get("task_dir", "")

    send_progress("📊 물량 데이터 로드 중...")

    # 현재 데이터 로드
    raw_data = _load_quantity_data()
    if not raw_data:
        return {
            "result_text": (
                "⚠️ 물량 데이터를 찾을 수 없습니다.\n\n"
                f"경로: {QUANTITY_DATA_FILE}\n"
                "p5-quantity-data.yaml 파일을 확인해주세요."
            ),
            "files": [],
        }

    current = _flatten_quantities(raw_data)
    if not current:
        return {
            "result_text": "⚠️ 물량 데이터에 숫자 값이 없습니다.",
            "files": [],
        }

    # 스냅샷 비교
    prev_snapshot = _load_latest_snapshot()

    now = datetime.now()
    lines = [
        f"📊 **선제작 물량 변동 감시 리포트**",
        f"━{'━' * 28}",
        f"📅 {now.strftime('%Y-%m-%d %H:%M')}",
        f"📁 데이터 항목: {len(current)}건",
        "",
    ]

    if prev_snapshot is None:
        # 첫 스냅샷
        lines.append("ℹ️ **첫 번째 스냅샷 생성** — 비교 대상 없음")
        lines.append("")
        lines.append("**현재 물량 데이터:**")
        for key, val in sorted(current.items()):
            lines.append(f"  {key}: {val:,.1f}")

        # 스냅샷 저장
        snap_path = _save_snapshot(raw_data)
        lines.append(f"\n💾 스냅샷 저장: {Path(snap_path).name}")
        lines.append("다음 실행 시부터 변동을 추적합니다.")

        return {"result_text": "\n".join(lines), "files": []}

    send_progress("📊 이전 스냅샷 대비 변동 분석 중...")

    previous = _flatten_quantities(prev_snapshot)
    changes = _calc_changes(current, previous)

    # 변동 분류
    significant = [c for c in changes if c.get("change_pct") is not None and abs(c["change_pct"]) >= CHANGE_THRESHOLD]
    minor = [c for c in changes if c.get("change_pct") is not None and abs(c["change_pct"]) < CHANGE_THRESHOLD]
    new_items = [c for c in changes if c.get("note") == "신규 항목"]
    deleted_items = [c for c in changes if c.get("note") == "삭제된 항목"]

    # 주요 변동 (임계값 초과)
    if significant:
        lines.append(f"🚨 **주요 변동 (±{CHANGE_THRESHOLD}% 이상)** — {len(significant)}건")
        for c in sorted(significant, key=lambda x: abs(x["change_pct"]), reverse=True):
            icon = "📈" if c["change_pct"] > 0 else "📉"
            lines.append(
                f"  {icon} {c['key']}: {c['previous']:,.1f} → {c['current']:,.1f} "
                f"({c['change_pct']:+.1f}%)"
            )
        lines.append("")
    else:
        lines.append("✅ **주요 변동 없음** (모든 항목 ±5% 이내)")
        lines.append("")

    # 소규모 변동
    if minor:
        lines.append(f"📊 **소규모 변동** ({len(minor)}건)")
        for c in minor[:10]:
            lines.append(
                f"  {c['key']}: {c['change_pct']:+.1f}%"
            )
        if len(minor) > 10:
            lines.append(f"  ... 외 {len(minor)-10}건")
        lines.append("")

    # 신규/삭제 항목
    if new_items:
        lines.append(f"🆕 **신규 항목** ({len(new_items)}건)")
        for c in new_items:
            lines.append(f"  {c['key']}: {c['current']:,.1f}")
        lines.append("")

    if deleted_items:
        lines.append(f"🗑️ **삭제된 항목** ({len(deleted_items)}건)")
        for c in deleted_items:
            lines.append(f"  {c['key']}: (이전 {c['previous']:,.1f})")
        lines.append("")

    # 스냅샷 저장
    snap_path = _save_snapshot(raw_data)
    lines.append(f"💾 새 스냅샷 저장: {Path(snap_path).name}")

    return {"result_text": "\n".join(lines), "files": []}
