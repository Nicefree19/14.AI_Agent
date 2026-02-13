"""
P5 데일리 브리핑 생성기
669줄 나열형 보고서 → 5~10개 핵심 항목 액션 브리핑

Usage:
    python p5_daily_briefing.py generate              # 오늘 브리핑
    python p5_daily_briefing.py generate --window 48  # 48시간 윈도우
    python p5_daily_briefing.py generate --stdout      # 콘솔만 (파일 미생성)
"""

import sys
import io
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, field

# Windows cp949 인코딩 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─── Configuration ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_PATH = PROJECT_ROOT / "ResearchVault"
INBOX_DIR = VAULT_PATH / "00-Inbox" / "Messages" / "Emails"
ISSUES_DIR = VAULT_PATH / "P5-Project" / "01-Issues"
OVERVIEW_DIR = VAULT_PATH / "P5-Project" / "00-Overview"

LOG_FILE = SCRIPT_DIR / "p5_daily_briefing.log"

# 로깅
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("p5_daily_briefing")


# ─── p5_email_triage 재사용 ─────────────────────────────────
# 같은 scripts/ 디렉토리에 있으므로 직접 import
from p5_email_triage import (
    TriageRules,
    EmailParser,
    TriageEngine,
    NoiseFilter,
    EmailData,
    TriageResult,
)


# ─── Data Classes ───────────────────────────────────────────
@dataclass
class BriefingItem:
    """브리핑 개별 항목"""

    title: str
    sender_org: str
    sender_name: str
    score: int
    priority: str
    action_needed: str
    source_type: str  # email | issue
    source_ref: str
    received_at: str
    categories: List[str] = field(default_factory=list)
    matched_issue: str = ""


@dataclass
class ActionItem:
    """오늘 할 일 개별 항목"""

    issue_id: str
    action_type: str  # respond_email | assign_owner | set_deadline | record_decision | review_queue
    description: str  # 한글 구체적 행동
    suggested_value: str  # 제안값 (담당자명, 날짜 등)
    priority: str  # critical/high/medium
    reason: str = ""  # 근거


@dataclass
class BriefingData:
    """브리핑 전체 데이터"""

    date: str
    window_hours: int
    action_items: List[ActionItem] = field(default_factory=list)
    critical_items: List[BriefingItem] = field(default_factory=list)
    high_items: List[BriefingItem] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    # Unified Dashboard Additions
    insights: List[str] = field(default_factory=list)
    critical_issues_list: List[Dict[str, str]] = field(default_factory=list)


# ─── Briefing Generator ────────────────────────────────────
class DailyBriefingGenerator:
    """데일리 브리핑 생성"""

    MAX_CRITICAL = 5
    MAX_HIGH = 5

    def __init__(self, rules: TriageRules):
        self.rules = rules
        self.parser = EmailParser(rules)
        self.engine = TriageEngine(rules)
        self.noise_filter = NoiseFilter(rules)

    def generate(self, window_hours: int = 24) -> BriefingData:
        """브리핑 데이터 생성"""
        today = datetime.now().strftime("%Y-%m-%d")
        data = BriefingData(date=today, window_hours=window_hours)

        # 1. 최근 이메일 수집 + 필터 + 트리아지
        emails = self._collect_recent_emails(window_hours)
        log.info(f"수집된 메일: {len(emails)}건 (최근 {window_hours}h)")

        # [Fallback] 이메일이 너무 적으면 검색 기간 확장 (최대 7일)
        if len(emails) < 3 and window_hours < 168:
            fallback_window = 168  # 7일
            log.info(
                f"💡 이메일 부족 ({len(emails)}건) → 검색 기간 확장 ({fallback_window}h)"
            )
            emails = self._collect_recent_emails(fallback_window)
            log.info(f"재수집된 메일: {len(emails)}건 (최근 {fallback_window}h)")

        total_input = len(emails)
        filtered_count = 0
        passed_items: List[BriefingItem] = []

        for email in emails:
            nf = self.noise_filter.filter(email)
            if nf.disposition != "pass":
                filtered_count += 1
                continue

            result = self.engine.triage(email)
            item = self._to_briefing_item(email, result)
            passed_items.append(item)

        # 2. 우선순위별 분류 (점수 내림차순)
        passed_items.sort(key=lambda x: x.score, reverse=True)

        for item in passed_items:
            if (
                item.priority == "critical"
                and len(data.critical_items) < self.MAX_CRITICAL
            ):
                data.critical_items.append(item)
            elif item.priority == "high" and len(data.high_items) < self.MAX_HIGH:
                data.high_items.append(item)

        # 3. 통계
        data.stats = {
            "total_emails": total_input,
            "noise_filtered": filtered_count,
            "valid_processed": len(passed_items),
            "critical_count": sum(1 for i in passed_items if i.priority == "critical"),
            "high_count": sum(1 for i in passed_items if i.priority == "high"),
            "medium_count": sum(1 for i in passed_items if i.priority == "medium"),
            "low_count": sum(1 for i in passed_items if i.priority == "low"),
        }

        # 4. "오늘 할 일" 액션 아이템 생성 (이메일 + 리스크)
        email_actions = self._generate_action_items(passed_items)
        risk_actions = self._collect_risk_action_items()

        # 4-1. 큐 건강도 red → 긴급 액션 아이템 추가
        try:
            from p5_metrics import calc_queue_health

            qh = calc_queue_health()
            if qh.get("status") == "red":
                risk_actions.append(
                    ActionItem(
                        issue_id="큐 건강도",
                        action_type="review_queue",
                        description=f"리뷰 큐 긴급 정리 필요: {qh['value']}",
                        suggested_value="미처리 항목 15건 초과",
                        priority="high",
                        reason=f"큐 건강도 🔴: {qh['detail']}",
                    )
                )
        except Exception:
            pass

        data.action_items = self._merge_action_items(
            email_actions, risk_actions, max_items=7
        )

        # 5. 경고사항 수집
        data.warnings = self._collect_warnings()

        # 6. [NEW] NotebookLM 인사이트 수집 (최근 24시간)
        data.insights = self._collect_recent_insights(window_hours)

        # 7. [NEW] 주요 미결 이슈 수집 (Critical/High)
        data.critical_issues_list = self._collect_open_issues()

        return data

    def _collect_recent_emails(self, window_hours: int) -> List[EmailData]:
        """최근 N시간 이내 이메일 수집"""
        if not INBOX_DIR.exists():
            return []

        emails = []
        cutoff = datetime.now() - timedelta(hours=window_hours)

        for mail_file in INBOX_DIR.glob("*.md"):
            email = self.parser.parse_email_file(mail_file)
            if not email:
                continue

            # 날짜 필터: 파일명에서 날짜 추출 시도
            try:
                # 파일명 형식: 20260206_outlook_...
                date_str = mail_file.stem[:8]
                file_date = datetime.strptime(date_str, "%Y%m%d")
                if file_date < cutoff:
                    continue
            except (ValueError, IndexError):
                pass  # 파싱 실패시 포함 (안전 측)

            emails.append(email)

        return emails

    def _collect_recent_insights(self, window_hours: int) -> List[str]:
        """최근 생성된 NotebookLM 인사이트 수집"""
        # NotebookLM 저장 위치: ResearchVault/03-Projects
        # 파일명 형식: YYYYMMDD-slug-insights.md
        target_dir = VAULT_PATH / "03-Projects"
        if not target_dir.exists():
            return []

        insights = []
        cutoff = datetime.now() - timedelta(hours=window_hours)
        cutoff_date_str = cutoff.strftime("%Y%m%d")

        for f in target_dir.glob("*-insights.md"):
            try:
                # 파일명 날짜 체크
                file_date_str = f.name[:8]
                if file_date_str < cutoff_date_str:
                    continue

                # 파일 내용 파싱 (제목, 요약 Extract)
                content = f.read_text(encoding="utf-8")
                lines = content.splitlines()
                title = f.stem
                summary = ""

                # H1 제목 추출
                for line in lines:
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break

                # 요약 섹션 추출 (간단히 첫 100자 정도)
                # "## 요약" 이후 줄
                in_summary = False
                for line in lines:
                    if line.startswith("## 요약"):
                        in_summary = True
                        continue
                    if in_summary and line.strip() and not line.startswith("#"):
                        summary = line.strip()
                        break
                    if in_summary and line.startswith("#"):
                        break

                insights.append(
                    f"🧠 **{title}**: {summary[:100]}..."
                    if summary
                    else f"🧠 **{title}**"
                )

            except Exception as e:
                log.error(f"인사이트 파싱 실패 ({f.name}): {e}")

        return insights[:5]  # 최대 5개

    def _collect_open_issues(self) -> List[Dict[str, str]]:
        """Vault에서 주요 미결 이슈(Critical/High) 수집"""
        if not ISSUES_DIR.exists():
            return []

        import yaml

        issues = []
        for f in ISSUES_DIR.glob("SEN-*.md"):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if not content.startswith("---"):
                    continue

                parts = content.split("---", 2)
                fm = yaml.safe_load(parts[1]) or {}

                status = fm.get("issue_status", "open")
                priority = fm.get("priority", "medium")

                # Filter: Open/InProgress AND Critical/High
                if status in ["open", "in_progress"] and priority in [
                    "critical",
                    "high",
                ]:
                    issues.append(
                        {
                            "id": f.stem,
                            "title": fm.get("title", "Untitled"),
                            "priority": priority,
                            "assignee": fm.get("assignee", "Unassigned"),
                        }
                    )

            except Exception:
                continue

        # Sort by priority (critical < high) -> 문자열 정렬상 critical이 앞섬
        issues.sort(key=lambda x: x["priority"])
        return issues[:5]

    def _to_briefing_item(self, email: EmailData, result: TriageResult) -> BriefingItem:
        """이메일+트리아지 → 브리핑 항목"""
        action = self._generate_action_summary(email, result)
        return BriefingItem(
            title=email.subject[:80],
            sender_org=result.sender_org,
            sender_name=result.sender_name,
            score=result.total_score,
            priority=result.priority,
            action_needed=action,
            source_type="email",
            source_ref=email.file_path.stem,
            received_at=email.received_at,
            categories=result.categories,
            matched_issue=result.matched_issue_id or "",
        )

    def _generate_action_summary(self, email: EmailData, result: TriageResult) -> str:
        """카테고리+키워드 기반 1줄 요약"""
        parts = []

        # 카테고리 기반 액션
        cat_actions = {
            "간섭": "간섭 검토 회신 필요",
            "구조접합": "접합부 검토/결정 필요",
            "일정": "일정 확인/조율 필요",
            "상세변경": "상세 변경 검토 필요",
            "설계": "설계 검토/승인 필요",
            "PC연동": "PC 연동 확인 필요",
        }

        for cat in result.categories:
            if cat in cat_actions:
                parts.append(cat_actions[cat])
                break

        # 행동 키워드 기반
        action_kw = result.keywords_hit
        if any(kw in ["긴급", "URGENT", "즉시", "ASAP"] for kw in action_kw):
            parts.insert(0, "긴급")
        elif any(kw in ["검토요청", "회신요청", "확인요청"] for kw in action_kw):
            if not parts:
                parts.append("검토 회신 필요")

        if not parts:
            if result.matched_issue_id:
                parts.append(f"이슈 {result.matched_issue_id} 업데이트 확인")
            else:
                parts.append("내용 확인 필요")

        return " / ".join(parts)

    def _generate_action_items(
        self, briefing_items: List[BriefingItem]
    ) -> List[ActionItem]:
        """이슈+메일 기반 오늘 할 일 생성"""
        actions: List[ActionItem] = []

        # 1. respond_email: score>=8인 메일 → 회신 필요
        for item in briefing_items:
            if item.score >= 8:
                sender = f"{item.sender_org} {item.sender_name}".strip()
                actions.append(
                    ActionItem(
                        issue_id=item.matched_issue or item.source_ref[:20],
                        action_type="respond_email",
                        description=f"메일 회신 필요: {item.title[:50]}",
                        suggested_value=sender,
                        priority=item.priority,
                        reason=f"score:{item.score}, 발신:{sender}",
                    )
                )

        # 2~4. 이슈 기반 액션: owner 없음, due_date 없음, decision 없음
        if ISSUES_DIR.exists():
            import yaml

            for f in ISSUES_DIR.glob("SEN-*.md"):
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if not content.startswith("---"):
                        continue
                    fm_end = content.index("---", 3)
                    fm = yaml.safe_load(content[3:fm_end])
                    if not fm:
                        continue

                    issue_id = fm.get("issue_id", f.stem)
                    priority = fm.get("priority", "")
                    if priority not in ("critical", "high"):
                        continue

                    owner = str(fm.get("owner", "")).strip()
                    due_date = str(fm.get("due_date", "")).strip()
                    decision = str(fm.get("decision", "")).strip()
                    action_plan = str(fm.get("action_plan", "")).strip()
                    source_origin = fm.get("source_origin", "")
                    title = fm.get("title", "")[:40]

                    # assign_owner: owner 빈 high/critical 이슈
                    if not owner:
                        suggested = self._suggest_owner(source_origin)
                        actions.append(
                            ActionItem(
                                issue_id=issue_id,
                                action_type="assign_owner",
                                description=f"담당자 지정: {title}",
                                suggested_value=suggested,
                                priority=priority,
                                reason=f"발생원: {source_origin or '미상'}",
                            )
                        )

                    # set_deadline: due_date 빈 high/critical 이슈
                    if not due_date:
                        suggested_due = fm.get("suggested_due_date", "")
                        actions.append(
                            ActionItem(
                                issue_id=issue_id,
                                action_type="set_deadline",
                                description=f"마감일 설정: {title}",
                                suggested_value=(
                                    str(suggested_due)
                                    if suggested_due
                                    else "7일 내 권장"
                                ),
                                priority=priority,
                                reason=f"High/Critical 이슈, 마감일 없음",
                            )
                        )

                    # record_decision: action_plan 있지만 decision 없음
                    if action_plan and not decision:
                        actions.append(
                            ActionItem(
                                issue_id=issue_id,
                                action_type="record_decision",
                                description=f"결정 기록 필요: {title}",
                                suggested_value=action_plan[:60],
                                priority=priority,
                                reason="action_plan 있으나 decision 없음",
                            )
                        )
                except Exception:
                    continue

        # 5. review_queue: 7일 이상 미처리 큐 항목 (파일 읽기)
        queue_path = OVERVIEW_DIR / "triage-review-queue.md"
        stale_queue = 0
        if queue_path.exists():
            today = datetime.now()
            for line in queue_path.read_text(encoding="utf-8").split("\n"):
                if not line.startswith("- [ ]"):
                    continue
                # 추가일 또는 날짜에서 연령 확인
                added_match = None
                if "추가일:" in line:
                    for part in line.split("|"):
                        if "추가일:" in part:
                            added_match = part.split("추가일:")[1].strip()[:10]
                            break
                elif "날짜:" in line:
                    for part in line.split("|"):
                        if "날짜:" in part:
                            added_match = part.split("날짜:")[1].strip()[:10]
                            break
                if added_match:
                    try:
                        age = (today - datetime.strptime(added_match, "%Y-%m-%d")).days
                        if age >= 7:
                            stale_queue += 1
                    except ValueError:
                        pass

        if stale_queue > 0:
            actions.append(
                ActionItem(
                    issue_id="리뷰 큐",
                    action_type="review_queue",
                    description=f"리뷰 큐 {stale_queue}건 7일 이상 미처리 → 이슈 연결 또는 폐기 결정",
                    suggested_value="",
                    priority="medium",
                    reason=f"{stale_queue}건 장기 미처리",
                )
            )

        # 우선순위 정렬: respond_email > assign_owner > set_deadline > record_decision > review_queue
        type_order = {
            "respond_email": 0,
            "assign_owner": 1,
            "set_deadline": 2,
            "record_decision": 3,
            "review_queue": 4,
        }
        prio_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        actions.sort(
            key=lambda a: (
                type_order.get(a.action_type, 9),
                prio_order.get(a.priority, 9),
            )
        )

        # Top 5만
        return actions[:5]

    def _collect_risk_action_items(self) -> List[ActionItem]:
        """리스크 매트릭스 Q1(즉시대응) 항목 → 액션 아이템"""
        try:
            from p5_risk_matrix import (
                load_issues,
                calculate_risk_score,
                determine_quadrant,
            )
        except ImportError:
            return []

        actions = []
        issues = load_issues()
        for issue in issues:
            urgency, impact = calculate_risk_score(issue)
            quad = determine_quadrant(urgency, impact)
            if quad != 1:  # Q1(즉시대응)만
                continue

            issue_id = issue.get("issue_id", "")
            title = issue.get("title", "")[:50]
            owner = issue.get("owner", "미지정")
            status = issue.get("issue_status", "open")

            if status in ("closed", "resolved"):
                continue

            actions.append(
                ActionItem(
                    issue_id=issue_id,
                    action_type="risk_response",
                    description=f"Q1 리스크 대응: {title}",
                    suggested_value=f"담당: {owner}" if owner else "담당자 지정 필요",
                    priority="critical",
                    reason=f"긴급도 {urgency:.1f} / 영향도 {impact:.1f}",
                )
            )

        return actions[:5]  # 최대 5건

    def _merge_action_items(
        self,
        email_actions: List[ActionItem],
        risk_actions: List[ActionItem],
        max_items: int = 7,
    ) -> List[ActionItem]:
        """이메일 + 리스크 액션 병합 (issue_id 기준 dedup)"""
        seen_ids = set()
        merged = []

        # risk가 우선 (Q1은 최고 우선순위)
        for a in risk_actions:
            if a.issue_id not in seen_ids:
                seen_ids.add(a.issue_id)
                merged.append(a)

        for a in email_actions:
            if a.issue_id not in seen_ids:
                seen_ids.add(a.issue_id)
                merged.append(a)

        # 정렬: critical > high > medium
        prio_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        merged.sort(key=lambda a: prio_order.get(a.priority, 9))
        return merged[:max_items]

    def _suggest_owner(self, source_origin: str) -> str:
        """source_origin 기반 담당 후보 제안"""
        origin_map = {
            "ENA(시공)": "ENA 현장담당",
            "삼성 E&A": "삼성E&A 담당",
            "센구조": "센구조 담당",
            "센구조/자체발견": "센구조 내부",
            "이앤디몰(PC)": "이앤디몰 확인",
        }
        if source_origin:
            for key, val in origin_map.items():
                if key in source_origin:
                    return val
        return "미정 - 발생원 확인"

    def _collect_warnings(self) -> List[str]:
        """경고사항 수집"""
        warnings = []

        # 미지정 이슈 카운트
        unassigned = 0
        no_deadline_high = 0
        total_issues = 0

        if ISSUES_DIR.exists():
            for f in ISSUES_DIR.glob("SEN-*.md"):
                total_issues += 1
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if "owner: " not in content and "owner:" not in content:
                        unassigned += 1
                    elif 'owner: ""' in content or "owner: ''" in content:
                        unassigned += 1

                    if 'due_date: ""' in content or "due_date: ''" in content:
                        # high/critical 판단은 triage_score로
                        if (
                            "triage_priority: high" in content
                            or "triage_priority: critical" in content
                        ):
                            no_deadline_high += 1
                except Exception:
                    pass

        if unassigned > 0:
            warnings.append(f"담당자 미지정 이슈: {unassigned}/{total_issues}건")
        if no_deadline_high > 0:
            warnings.append(f"마감일 없는 High/Critical: {no_deadline_high}건")

        # ── 운영 메트릭 건강도 경고 추가 ──
        try:
            from p5_metrics import (
                calc_snr,
                calc_triage_accuracy,
                calc_decision_velocity,
                calc_queue_health,
                calc_data_completeness,
            )

            health_metrics = [
                calc_snr(),
                calc_triage_accuracy(),
                calc_decision_velocity(),
                calc_queue_health(),
                calc_data_completeness(),
            ]
            for m in health_metrics:
                status = m.get("status", "")
                name = m.get("name", "")
                value = m.get("value", "")
                if status == "red":
                    warnings.append(f"🔴 {name}: {value} — 즉시 조치 필요")
                elif status == "yellow":
                    warnings.append(f"🟡 {name}: {value} — 주의")
        except ImportError:
            pass  # p5_metrics 없으면 skip
        except Exception:
            pass

        return warnings


# ─── Markdown Renderer ──────────────────────────────────────
def render_briefing_markdown(data: BriefingData) -> str:
    """브리핑 데이터 → 마크다운 (Unified Dashboard)"""
    lines = [
        "---",
        f"title: P5 데일리 브리핑 - {data.date}",
        f"date: {data.date}",
        "tags: [project/p5, type/briefing]",
        "---",
        "",
        f"# 📅 P5 Daily Briefing ({data.date})",
        f"> **Focus**: {len(data.action_items)} Actions | {len(data.critical_items)} Critical Emails",
        "",
    ]

    # 1. 🚨 Critical Issues (Top 5)
    if data.critical_issues_list:
        lines.append("## 🚨 주요 미결 이슈 (Critical/High)")
        lines.append("| ID | 제목 | 담당자 | 중요도 |")
        lines.append("|---|---|---|---|")
        for issue in data.critical_issues_list:
            icon = "🔴" if issue["priority"] == "critical" else "🟠"
            lines.append(
                f"| {issue['id']} | {issue['title']} | {issue['assignee']} | {icon} |"
            )
        lines.append("")

    # 2. ✅ Today's Actions
    if data.action_items:
        lines.append("## ✅ 오늘의 할 일 (Top Actions)")
        for i, act in enumerate(data.action_items, 1):

            icon = (
                "🔥"
                if act.priority == "critical"
                else "⚡" if act.priority == "high" else "🔹"
            )
            suggested = f" → {act.suggested_value}" if act.suggested_value else ""
            lines.append(
                f"{i}. {icon} **[{act.action_type}]** {act.description}{suggested}"
            )
            value_str = f"🔗 {act.issue_id}"
            if act.reason:
                value_str += f" | {act.reason}"
            lines.append(f"   - {value_str}")

    else:
        lines.append("## ✅ 오늘의 할 일")
        lines.append("_(특별한 액션 아이템이 없습니다)_")
    lines.append("")

    # 3. 🧠 NotebookLM Insights
    if data.insights:
        lines.append("## 🧠 최신 AI 인사이트 (NotebookLM)")
        for insight in data.insights:
            lines.append(f"- {insight}")
        lines.append("")

    # 4. 📧 Critical Emails
    if data.critical_items:
        lines.append("## 📧 중요 수신 메일 (Critical/High)")
        for item in data.critical_items:
            sender = f"{item.sender_org} {item.sender_name}".strip()
            lines.append(f"- 🔴 **[{sender}]** {item.title}")
            lines.append(f"  - Action: {item.action_needed}")
            if item.source_ref:
                lines.append(f"  - Ref: {item.source_ref}")
        lines.append("")

    # 5. Stats & Warnings
    lines.append("---")
    s = data.stats
    lines.append(
        f"**Stats**: 📩 수신 {s.get('total_emails', 0)} | 🗑️ 필터 {s.get('noise_filtered', 0)} | ✅ 처리 {s.get('valid_processed', 0)}"
    )

    if data.warnings:
        lines.append("")
        lines.append("**⚠️ System Warnings**")
        for w in data.warnings:
            lines.append(f"- {w}")

    return "\n".join(lines)


# ─── Commands ───────────────────────────────────────────────
def cmd_generate(args):
    """브리핑 생성"""
    log.info("=" * 50)
    log.info("P5 데일리 브리핑 생성")
    log.info("=" * 50)

    rules = TriageRules()
    generator = DailyBriefingGenerator(rules)

    window = getattr(args, "window", 24) or 24
    data = generator.generate(window_hours=window)
    md = render_briefing_markdown(data)

    # stdout 출력 여부
    if getattr(args, "stdout", False):
        print(md)
    else:
        # 파일 생성 (stdout이 아닐 때만)
        today = datetime.now().strftime("%Y-%m-%d")
        output_path = OVERVIEW_DIR / f"데일리브리핑-{today}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(md, encoding="utf-8")
        log.info(f"브리핑 생성: {output_path}")

    # 콘솔에도 요약 출력 (stdout 모드 아닐 때만 로그로)
    s = data.stats
    if not getattr(args, "stdout", False):
        log.info(
            f"  입력: {s.get('total_emails', 0)}건 | 필터: {s.get('noise_filtered', 0)}건 | 유효: {s.get('valid_processed', 0)}건"
        )
        log.info(
            f"  Critical: {s.get('critical_count', 0)} | High: {s.get('high_count', 0)} | Medium: {s.get('medium_count', 0)}"
        )

    # 텔레그램 전송
    if getattr(args, "push", False):
        log.info("텔레그램 전송 시도...")
        try:
            # sys.path 조정으로 telegram 모듈 임포트 가능하게 함 (필요시)
            if str(SCRIPT_DIR) not in sys.path:
                sys.path.append(str(SCRIPT_DIR))

            from telegram.telegram_sender import send_message_sync
            from dotenv import load_dotenv
            import os

            env_path = PROJECT_ROOT / ".env"
            load_dotenv(env_path)

            # .env에서 ID 가져오기 (콤마로 구분된 첫 번째 ID 사용)
            allowed_users_str = os.getenv("TELEGRAM_ALLOWED_USERS", "")
            if not allowed_users_str:
                log.error("TELEGRAM_ALLOWED_USERS 환경변수가 없습니다.")
                return

            # 첫 번째 사용자를 수신자로 지정
            chat_id = allowed_users_str.split(",")[0].strip()
            if not chat_id:
                log.error("유효한 채팅 ID를 찾을 수 없습니다.")
                return

            log.info(f"전송 대상: {chat_id}")

            # 메시지 전송 (Markdown)
            # send_message_sync 함수가 자동으로 긴 메시지를 분할 전송함
            success = send_message_sync(chat_id, md)

            if success:
                log.info("✅ 텔레그램 전송 성공")
            else:
                log.error("❌ 텔레그램 전송 실패")

        except ImportError as ie:
            log.error(f"모듈 임포트 실패: {ie}")
            log.error("scripts/telegram/telegram_sender.py가 존재하는지 확인하세요.")
        except Exception as e:
            log.error(f"텔레그램 전송 중 오류: {e}")


def main():
    parser = argparse.ArgumentParser(description="P5 데일리 브리핑 생성기")
    sub = parser.add_subparsers(dest="command", help="명령어")

    p_gen = sub.add_parser("generate", help="브리핑 생성")
    p_gen.add_argument("--window", type=int, default=24, help="시간 윈도우 (기본 24h)")
    p_gen.add_argument(
        "--stdout", action="store_true", help="콘솔만 출력 (파일 미생성)"
    )
    p_gen.add_argument("--push", action="store_true", help="텔레그램으로 브리핑 전송")
    p_gen.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
