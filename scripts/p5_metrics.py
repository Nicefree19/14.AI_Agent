"""
P5 운영 메트릭 대시보드
5개 핵심 지표 계산 + 마크다운 대시보드 생성

Usage:
    python p5_metrics.py generate           # 메트릭 대시보드 생성
    python p5_metrics.py generate --stdout  # 콘솔만 출력
"""

import sys
import io
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# Windows cp949 인코딩 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import yaml

# ─── Configuration ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_PATH = PROJECT_ROOT / "ResearchVault"
ISSUES_DIR = VAULT_PATH / "P5-Project" / "01-Issues"
DECISIONS_DIR = VAULT_PATH / "P5-Project" / "04-Decisions"
OVERVIEW_DIR = VAULT_PATH / "P5-Project" / "00-Overview"
INBOX_DIR = VAULT_PATH / "00-Inbox" / "Messages" / "Emails"
SYNC_CONFIG_PATH = VAULT_PATH / "_config" / "p5-sync-config.yaml"
LOG_FILE = SCRIPT_DIR / "p5_metrics.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("p5_metrics")


# ─── Helpers ────────────────────────────────────────────────
def _parse_frontmatter(file_path: Path) -> dict:
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def _load_config() -> dict:
    if not SYNC_CONFIG_PATH.exists():
        return {}
    try:
        with open(SYNC_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# ─── Metric Calculators ────────────────────────────────────
def calc_snr() -> Dict:
    """1. 신호대잡음비 — 이메일 중 유효 처리 비율"""
    total = 0
    noise = 0

    # 최근 이메일 파일 분석 (간접 측정)
    if INBOX_DIR.exists():
        total = len(list(INBOX_DIR.glob("*.md")))

    # 트리아지 로그에서 필터링 비율 추정
    # (실제로는 process 실행 시 기록됨, 여기서는 이메일 파일 기반 추정)
    # 노이즈 키워드로 간접 판단
    noise_indicators = ["linkedin", "noreply", "용인단지", "우리들교회", "리마건축"]
    if INBOX_DIR.exists():
        for f in INBOX_DIR.glob("*.md"):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")[:500].lower()
                if any(kw.lower() in content for kw in noise_indicators):
                    noise += 1
            except Exception:
                pass

    passed = total - noise
    snr = round(passed / max(total, 1) * 100)
    return {
        "name": "신호대잡음비 (SNR)",
        "value": f"{snr}%",
        "detail": f"입력 {total}건 / 유효 {passed}건 / 노이즈 {noise}건",
        "status": "green" if snr >= 60 else "yellow" if snr >= 40 else "red",
    }


def calc_triage_accuracy() -> Dict:
    """2. 트리아지 정확도 — 이슈 매칭 성공률"""
    triaged = 0
    matched = 0

    if ISSUES_DIR.exists():
        for f in ISSUES_DIR.glob("SEN-*.md"):
            fm = _parse_frontmatter(f)
            if fm.get("triage_score"):
                triaged += 1
                # triage_score가 있고 matched_issue 정보가 있으면 매칭 성공
                matched += 1  # 현재는 triage가 된 것 자체를 매칭 성공으로 간주

    rate = round(triaged / max(triaged + 1, 1) * 100) if triaged > 0 else 0
    return {
        "name": "트리아지 커버리지",
        "value": f"{triaged}건",
        "detail": f"전체 이슈 중 트리아지 완료: {triaged}건",
        "status": "green" if triaged > 50 else "yellow" if triaged > 10 else "red",
    }


def calc_decision_velocity() -> Dict:
    """3. 의사결정 속도 — 결정 기록 수"""
    total_decisions = 0
    recent_decisions = 0

    if DECISIONS_DIR.exists():
        dec_files = list(DECISIONS_DIR.glob("DEC-*.md"))
        total_decisions = len(dec_files)

        # 최근 7일 이내 결정
        cutoff = datetime.now().strftime("%Y%m%d")
        for f in dec_files:
            try:
                date_part = f.stem.split("-")[1]  # DEC-YYYYMMDD-NNN
                if date_part >= (datetime.now().replace(day=max(1, datetime.now().day - 7))).strftime("%Y%m%d"):
                    recent_decisions += 1
            except (IndexError, ValueError):
                pass

    return {
        "name": "의사결정 속도",
        "value": f"{total_decisions}건 (주간 {recent_decisions}건)",
        "detail": f"총 결정 기록: {total_decisions}건",
        "status": "green" if recent_decisions >= 3 else "yellow" if recent_decisions >= 1 else "red",
    }


def calc_queue_health() -> Dict:
    """4. 큐 건강도 — 대기 항목 수"""
    queue_path = OVERVIEW_DIR / "triage-review-queue.md"
    total = 0
    unchecked = 0

    if queue_path.exists():
        content = queue_path.read_text(encoding="utf-8")
        for line in content.split("\n"):
            if line.startswith("- ["):
                total += 1
                if line.startswith("- [ ]"):
                    unchecked += 1

    return {
        "name": "큐 건강도",
        "value": f"{unchecked}/{total}건 미처리",
        "detail": f"총 {total}건 / 미처리 {unchecked}건 / 처리 {total - unchecked}건",
        "status": "green" if unchecked <= 5 else "yellow" if unchecked <= 15 else "red",
    }


def calc_data_completeness() -> Dict:
    """5. 데이터 완전성 — owner/due_date/decision 비율"""
    total = 0
    has_owner = 0
    has_due = 0
    has_decision = 0

    if ISSUES_DIR.exists():
        for f in ISSUES_DIR.glob("SEN-*.md"):
            fm = _parse_frontmatter(f)
            total += 1

            owner = str(fm.get("owner", "")).strip()
            if owner and owner != "''":
                has_owner += 1

            due = str(fm.get("due_date", "")).strip()
            if due and due != "''":
                has_due += 1

            dec = str(fm.get("decision", "")).strip()
            if dec and dec != "''":
                has_decision += 1

    pct_owner = round(has_owner / max(total, 1) * 100)
    pct_due = round(has_due / max(total, 1) * 100)
    pct_dec = round(has_decision / max(total, 1) * 100)
    avg = round((pct_owner + pct_due + pct_dec) / 3)

    return {
        "name": "데이터 완전성",
        "value": f"{avg}%",
        "detail": f"담당자 {pct_owner}% / 마감일 {pct_due}% / 결정사항 {pct_dec}%",
        "status": "green" if avg >= 50 else "yellow" if avg >= 20 else "red",
        "breakdown": {"owner": pct_owner, "due_date": pct_due, "decision": pct_dec},
    }


def calc_auto_apply_accuracy() -> Dict:
    """6. 자동적용 정확도 — audit log 기반 정확도 추적"""
    audit_path = OVERVIEW_DIR / "triage-audit-log.jsonl"
    total = 0
    corrections = 0

    if audit_path.exists():
        import json
        for line in audit_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                total += 1
                if entry.get("corrected", False):
                    corrections += 1
            except Exception:
                continue

    if total == 0:
        return {
            "name": "자동적용 정확도",
            "value": "N/A (데이터 없음)",
            "detail": "audit 로그 0건 — 자동적용 미실행",
            "status": "yellow",
            "accuracy": 0,
            "sample_count": 0,
        }

    accuracy = round((total - corrections) / total * 100)
    return {
        "name": "자동적용 정확도",
        "value": f"{accuracy}% ({total}건 중 수정 {corrections}건)",
        "detail": f"총 {total}건 자동적용 / {corrections}건 수동 수정",
        "status": "green" if accuracy >= 90 else "yellow" if accuracy >= 80 else "red",
        "accuracy": accuracy,
        "sample_count": total,
    }


def calc_classification_distribution() -> Dict:
    """7. 분류 분포 — Action/Decision/Reference/Trash 비율"""
    dist = {"Action": 0, "Decision": 0, "Reference": 0, "Trash": 0}
    total = 0

    if ISSUES_DIR.exists():
        for f in ISSUES_DIR.glob("SEN-*.md"):
            fm = _parse_frontmatter(f)
            cls = fm.get("classification", "")
            if cls in dist:
                dist[cls] += 1
                total += 1

    if total == 0:
        return {
            "name": "분류 분포",
            "value": "데이터 없음",
            "detail": "classification 필드가 있는 이슈 없음",
            "status": "yellow",
        }

    parts = " / ".join(f"{k[0]}:{v}" for k, v in dist.items())
    action_pct = round((dist["Action"] + dist["Decision"]) / max(total, 1) * 100)
    return {
        "name": "분류 분포",
        "value": parts,
        "detail": f"총 {total}건 | 실행율(A+D) {action_pct}% | A:{dist['Action']} D:{dist['Decision']} R:{dist['Reference']} T:{dist['Trash']}",
        "status": "green" if action_pct >= 30 else "yellow" if action_pct >= 10 else "red",
    }


def calc_tier_distribution() -> Dict:
    """보너스: 계층 분포"""
    config = _load_config()
    tiered = config.get("tiered_sync", {})

    t1 = t2 = t3 = 0
    total = 0

    if ISSUES_DIR.exists() and tiered.get("enabled", False):
        # 간단한 인라인 tier 분류 (p5_issue_sync 의존 제거)
        for f in ISSUES_DIR.glob("SEN-*.md"):
            fm = _parse_frontmatter(f)
            total += 1
            status = fm.get("issue_status", "open")
            priority = fm.get("priority", "medium")

            if status in ("closed", "resolved"):
                t3 += 1
            elif priority in ("critical", "high") and status in ("open", "in_progress"):
                t1 += 1
            else:
                t2 += 1

    return {
        "name": "계층 분포",
        "value": f"T1={t1} / T2={t2} / T3={t3}",
        "detail": f"Active {t1}건 / Watch {t2}건 / Archive {t3}건 (총 {total}건)",
    }


# ─── Dashboard Renderer ────────────────────────────────────
def render_metrics_dashboard(metrics: List[Dict]) -> str:
    """메트릭 리스트 → 마크다운 대시보드"""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    status_icons = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

    lines = [
        "---",
        f"title: P5 운영 메트릭",
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "tags: [project/p5, type/metrics]",
        "---",
        "",
        f"# P5 운영 메트릭 대시보드",
        f"> 마지막 업데이트: {today}",
        "",
        "## 핵심 지표",
        "",
        "| 지표 | 상태 | 값 | 상세 |",
        "|------|:----:|-----|------|",
    ]

    for m in metrics:
        icon = status_icons.get(m.get("status", ""), "⚪")
        lines.append(f"| {m['name']} | {icon} | {m['value']} | {m['detail']} |")

    lines.append("")

    # 데이터 완전성 세부
    for m in metrics:
        if m["name"] == "데이터 완전성" and "breakdown" in m:
            bd = m["breakdown"]
            lines.extend([
                "## 데이터 완전성 세부",
                "",
                "```",
                f"담당자(owner):    {'█' * (bd['owner'] // 5)}{'░' * (20 - bd['owner'] // 5)} {bd['owner']}%",
                f"마감일(due_date): {'█' * (bd['due_date'] // 5)}{'░' * (20 - bd['due_date'] // 5)} {bd['due_date']}%",
                f"결정(decision):   {'█' * (bd['decision'] // 5)}{'░' * (20 - bd['decision'] // 5)} {bd['decision']}%",
                "```",
                "",
            ])

    return "\n".join(lines)


# ─── Command ───────────────────────────────────────────────
def cmd_generate(args):
    """메트릭 대시보드 생성"""
    log.info("=" * 50)
    log.info("P5 운영 메트릭 생성")
    log.info("=" * 50)

    metrics = [
        calc_snr(),
        calc_triage_accuracy(),
        calc_decision_velocity(),
        calc_queue_health(),
        calc_data_completeness(),
        calc_auto_apply_accuracy(),
        calc_classification_distribution(),
        calc_tier_distribution(),
    ]

    md = render_metrics_dashboard(metrics)

    if getattr(args, "stdout", False):
        print(md)
        return

    output_path = OVERVIEW_DIR / "운영메트릭.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")
    log.info(f"메트릭 대시보드 생성: {output_path}")

    for m in metrics:
        status_icons = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
        icon = status_icons.get(m.get("status", ""), "⚪")
        log.info(f"  {icon} {m['name']}: {m['value']}")


def main():
    parser = argparse.ArgumentParser(description="P5 운영 메트릭 대시보드")
    sub = parser.add_subparsers(dest="command", help="명령어")

    p_gen = sub.add_parser("generate", help="메트릭 생성")
    p_gen.add_argument("--stdout", action="store_true", help="콘솔만 출력")
    p_gen.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
