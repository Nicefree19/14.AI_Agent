"""
P5 리스크 매트릭스 생성기
이슈 데이터를 분석하여 Mermaid quadrant chart 기반 리스크 매트릭스 자동 생성

Usage:
    python p5_risk_matrix.py generate       # 매트릭스 갱신
    python p5_risk_matrix.py export         # Mermaid 코드 출력
    python p5_risk_matrix.py action-items   # SS-Splice/Y-1 액션아이템 추출
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple
from dataclasses import dataclass

import yaml

# ─── Configuration ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_PATH = PROJECT_ROOT / "ResearchVault"
ISSUES_DIR = VAULT_PATH / "P5-Project" / "01-Issues"
OUTPUT_DIR = VAULT_PATH / "P5-Project" / "00-Overview"


# ─── Data Classes ───────────────────────────────────────────
@dataclass
class RiskItem:
    """리스크 항목"""

    issue_id: str
    title: str
    urgency: float  # 0-1
    impact: float  # 0-1
    priority: str
    category: str
    owner: str
    due_date: str
    quadrant: int  # 1-4


# ─── Priority to Score Mapping ──────────────────────────────
PRIORITY_URGENCY = {
    "critical": 0.9,
    "high": 0.7,
    "medium": 0.5,
    "normal": 0.4,
    "low": 0.2,
}

CATEGORY_IMPACT = {
    "구조접합": 0.9,
    "간섭": 0.85,
    "psrc": 0.85,
    "hmb": 0.8,
    "설계": 0.75,
    "pc연동": 0.7,
    "일정": 0.6,
    "상세변경": 0.5,
    "해당없음": 0.3,
}


# ─── Issue Loader ───────────────────────────────────────────
def load_issues() -> List[Dict]:
    """이슈 파일 로드"""
    issues = []
    for f in ISSUES_DIR.glob("*.md"):
        if f.name.startswith("20"):  # 인덱스 파일 제외
            continue
        try:
            content = f.read_text(encoding="utf-8")
            if not content.startswith("---"):
                continue
            parts = content.split("---", 2)
            if len(parts) >= 2:
                fm = yaml.safe_load(parts[1]) or {}
                if fm.get("issue_id"):
                    issues.append(fm)
        except Exception:
            pass
    return issues


def calculate_risk_score(issue: Dict) -> Tuple[float, float]:
    """긴급도/영향도 점수 계산"""
    priority = issue.get("priority", "medium").lower()
    category = issue.get("category", "").lower()

    # 긴급도 (마감일, 우선순위 기반)
    urgency = PRIORITY_URGENCY.get(priority, 0.5)
    due_date = issue.get("due_date", "")
    if due_date:
        # 마감일이 있으면 긴급도 +0.1
        urgency = min(1.0, urgency + 0.1)

    # 영향도 (카테고리 기반)
    impact = 0.5
    for cat_key, cat_impact in CATEGORY_IMPACT.items():
        if cat_key in category:
            impact = max(impact, cat_impact)
            break

    return urgency, impact


def determine_quadrant(urgency: float, impact: float) -> int:
    """사분면 결정 (1=즉시대응, 2=계획수립, 3=모니터링, 4=일정조율)"""
    if urgency >= 0.6 and impact >= 0.6:
        return 1  # 즉시 대응
    elif urgency < 0.6 and impact >= 0.6:
        return 2  # 계획 수립
    elif urgency < 0.6 and impact < 0.6:
        return 3  # 모니터링
    else:
        return 4  # 일정 조율


# ─── Mermaid Generator ──────────────────────────────────────
def generate_mermaid_chart(items: List[RiskItem], max_items: int = 15) -> str:
    """Mermaid quadrant chart 생성"""
    lines = [
        '%%{init: {"quadrantChart": {"chartWidth": 500, "chartHeight": 500}}}%%',
        "quadrantChart",
        "    title P5 이슈 리스크 매트릭스",
        "    x-axis 낮은 긴급도 --> 높은 긴급도",
        "    y-axis 낮은 영향도 --> 높은 영향도",
        "    quadrant-1 🔥 즉시 대응",
        "    quadrant-2 📋 계획 수립",
        "    quadrant-3 👀 모니터링",
        "    quadrant-4 ⏰ 일정 조율",
        "",
    ]

    # 상위 N개 항목만 표시
    top_items = sorted(items, key=lambda x: (x.urgency + x.impact), reverse=True)[
        :max_items
    ]

    for item in top_items:
        # 제목 축약 (20자)
        short_title = item.title[:20].replace('"', "'")
        if len(item.title) > 20:
            short_title += "..."
        lines.append(f'    "{short_title}": [{item.urgency:.2f}, {item.impact:.2f}]')

    return "\n".join(lines)


# ─── Action Items Extractor ─────────────────────────────────
def extract_action_items() -> str:
    """SS-Splice/Y-1 관련 액션아이템 추출"""
    issues = load_issues()

    ss_splice_items = []
    y1_items = []

    for issue in issues:
        title = issue.get("title", "").lower()
        category = issue.get("category", "").lower()

        if "ss-splice" in title or "기둥이음" in title or "splice" in category:
            ss_splice_items.append(issue)
        elif "y-1" in title or "y1" in title or "공통랙" in title:
            y1_items.append(issue)

    lines = [
        "---",
        "title: SS-Splice / Y-1 액션아이템",
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "tags: [project/p5, type/action-items]",
        "---",
        "",
        "# 🔧 SS-Splice / Y-1 액션아이템",
        "",
        f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## 🔩 SS-Splice 관련",
        "",
    ]

    if ss_splice_items:
        lines.append("| 이슈 | 상태 | 담당자 | 마감일 |")
        lines.append("|------|------|--------|--------|")
        for item in ss_splice_items[:10]:
            iid = item.get("issue_id", "")
            title = item.get("title", "")[:40]
            status = item.get("issue_status", "")
            owner = item.get("owner", "-")
            due = item.get("due_date", "-")
            lines.append(f"| [[{iid}\\|{title}]] | {status} | {owner} | {due} |")
    else:
        lines.append("_관련 이슈 없음_")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 📦 Y-1 공통랙 관련",
            "",
        ]
    )

    if y1_items:
        lines.append("| 이슈 | 상태 | 담당자 | 마감일 |")
        lines.append("|------|------|--------|--------|")
        for item in y1_items[:10]:
            iid = item.get("issue_id", "")
            title = item.get("title", "")[:40]
            status = item.get("issue_status", "")
            owner = item.get("owner", "-")
            due = item.get("due_date", "-")
            lines.append(f"| [[{iid}\\|{title}]] | {status} | {owner} | {due} |")
    else:
        lines.append("_관련 이슈 없음_")

    return "\n".join(lines)


# ─── Commands ───────────────────────────────────────────────
def cmd_generate(args):
    """리스크 매트릭스 생성"""
    print("리스크 매트릭스 생성 중...")

    issues = load_issues()
    print(f"로드된 이슈: {len(issues)}개")

    items = []
    for issue in issues:
        status = issue.get("issue_status", "").lower()
        if status in ["closed", "resolved"]:
            continue

        urgency, impact = calculate_risk_score(issue)
        quadrant = determine_quadrant(urgency, impact)

        items.append(
            RiskItem(
                issue_id=issue.get("issue_id", ""),
                title=issue.get("title", ""),
                urgency=urgency,
                impact=impact,
                priority=issue.get("priority", ""),
                category=issue.get("category", ""),
                owner=issue.get("owner", ""),
                due_date=issue.get("due_date", ""),
                quadrant=quadrant,
            )
        )

    # 사분면별 집계
    quadrant_count = {1: 0, 2: 0, 3: 0, 4: 0}
    for item in items:
        quadrant_count[item.quadrant] += 1

    print("\n사분면별 분포:")
    print(f"  Q1 (즉시대응): {quadrant_count[1]}개")
    print(f"  Q2 (계획수립): {quadrant_count[2]}개")
    print(f"  Q3 (모니터링): {quadrant_count[3]}개")
    print(f"  Q4 (일정조율): {quadrant_count[4]}개")

    # Mermaid 차트 생성
    mermaid = generate_mermaid_chart(items)
    print("\nMermaid 코드 생성 완료")

    if args.output:
        Path(args.output).write_text(mermaid, encoding="utf-8")
        print(f"저장: {args.output}")


def cmd_export(args):
    """Mermaid 코드 출력"""
    issues = load_issues()
    items = []

    for issue in issues:
        status = issue.get("issue_status", "").lower()
        if status in ["closed", "resolved"]:
            continue

        urgency, impact = calculate_risk_score(issue)
        items.append(
            RiskItem(
                issue_id=issue.get("issue_id", ""),
                title=issue.get("title", ""),
                urgency=urgency,
                impact=impact,
                priority=issue.get("priority", ""),
                category=issue.get("category", ""),
                owner=issue.get("owner", ""),
                due_date=issue.get("due_date", ""),
                quadrant=determine_quadrant(urgency, impact),
            )
        )

    mermaid = generate_mermaid_chart(items)
    print(mermaid)


def cmd_action_items(args):
    """액션아이템 추출"""
    print("SS-Splice/Y-1 액션아이템 추출 중...")

    content = extract_action_items()

    output_path = OUTPUT_DIR / "20260207-액션아이템-SS-Splice-Y1.md"
    output_path.write_text(content, encoding="utf-8")

    print(f"저장: {output_path}")


# ─── Main ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="P5 리스크 매트릭스 생성기")
    sub = parser.add_subparsers(dest="command")

    # generate
    p_gen = sub.add_parser("generate", help="리스크 매트릭스 생성")
    p_gen.add_argument("--output", help="출력 파일 경로")
    p_gen.set_defaults(func=cmd_generate)

    # export
    p_exp = sub.add_parser("export", help="Mermaid 코드 출력")
    p_exp.set_defaults(func=cmd_export)

    # action-items
    p_act = sub.add_parser("action-items", help="액션아이템 추출")
    p_act.set_defaults(func=cmd_action_items)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
