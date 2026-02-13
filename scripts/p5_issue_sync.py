"""
P5 이슈 동기화 스크립트
Google Sheets API를 통해 AppSheet 이슈 데이터를 Obsidian Vault로 동기화

Usage:
    python p5_issue_sync.py sync              # Google Sheets에서 동기화
    python p5_issue_sync.py sync --csv FILE   # CSV 파일에서 동기화 (fallback)
    python p5_issue_sync.py archive --dry-run # 수명주기 분석 (미리보기)
    python p5_issue_sync.py archive           # 수명주기 적용 (상태 전이)
    python p5_issue_sync.py status            # 동기화 상태 확인
    python p5_issue_sync.py setup             # API 설정 안내
"""

import sys
import io
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

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
CONFIG_PATH = VAULT_PATH / "_config" / "p5-sync-config.yaml"
CREDENTIALS_PATH = PROJECT_ROOT / ".secrets" / "google-sheets-credentials.json"
LOG_FILE = SCRIPT_DIR / "p5_issue_sync.log"

# Google Sheets 설정 (사용자가 수정해야 함)
DEFAULT_SPREADSHEET_ID = ""  # Google Sheets URL에서 추출
DEFAULT_SHEET_NAME = "이슈목록"

# 이슈 스키마 매핑 (Google Sheets 컬럼 → Frontmatter 필드)
# 실제 '접수 메일' 시트 컬럼명과 일치해야 함 (p5-sync-config.yaml 참조)
COLUMN_MAPPING = {
    "NO": "issue_id",
    "이슈명": "title",
    "상태": "issue_status",
    "담당자": "owner",
    "마감일": "due_date",
    "긴급도": "priority",
    "공법구분": "category",
    "상세내용(Spec)": "description",
    "관련도면": "related_docs",
    "수신일": "created_at",
    "위치(Zone)": "zone",
    "발생원": "source_origin",
    "조치계획": "action_plan",
    "결정사항": "decision",
}

# 상태 매핑 (한글 → 영문)
STATUS_MAPPING = {
    "열림": "open",
    "진행중": "in_progress",
    "완료": "resolved",
    "종료": "closed",
    "보류": "on_hold",
}

# 우선순위 매핑
PRIORITY_MAPPING = {
    "긴급": "critical",
    "높음": "high",
    "중간": "medium",
    "낮음": "low",
}

# 카테고리 매핑
CATEGORY_MAPPING = {
    "구조": "structure",
    "일정": "schedule",
    "자재": "material",
    "설계": "design",
    "간섭": "interference",
    "협의": "coordination",
}


# ─── Logging Setup ──────────────────────────────────────────
def setup_logging(debug: bool = False) -> logging.Logger:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("p5_issue_sync")


log = setup_logging()


# ─── Data Classes ───────────────────────────────────────────
@dataclass
class Issue:
    """이슈 데이터 클래스"""

    issue_id: str
    title: str
    issue_status: str = "open"
    owner: str = ""
    due_date: str = ""
    priority: str = "medium"
    category: str = "general"
    description: str = ""
    related_docs: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    source_file: str = ""
    last_synced_at: str = ""
    zone: str = ""
    source_origin: str = ""
    action_plan: str = ""
    decision: str = ""

    def to_frontmatter(self) -> dict:
        """YAML frontmatter 딕셔너리로 변환"""
        return {
            "issue_id": self.issue_id,
            "title": self.title,
            "issue_status": self.issue_status,
            "owner": self.owner,
            "due_date": self.due_date,
            "priority": self.priority,
            "category": self.category,
            "zone": self.zone,
            "source_origin": self.source_origin,
            "action_plan": self.action_plan,
            "decision": self.decision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_file": self.source_file,
            "last_synced_at": self.last_synced_at,
            "tags": [
                "project/p5",
                "type/issue",
                f"status/{self.issue_status}",
                f"priority/{self.priority}",
                f"category/{self.category}",
            ],
        }

    def to_markdown(self) -> str:
        """전체 마크다운 문서 생성"""
        fm = self.to_frontmatter()

        lines = ["---"]
        lines.append(
            yaml.dump(
                fm, allow_unicode=True, default_flow_style=False, sort_keys=False
            ).rstrip()
        )
        lines.append("---")
        lines.append("")
        lines.append(f"# {self.title}")
        lines.append("")

        # 메타 정보 테이블
        lines.append("## 📋 기본 정보")
        lines.append("")
        lines.append("| 항목 | 내용 |")
        lines.append("|------|------|")
        lines.append(f"| **이슈 ID** | `{self.issue_id}` |")
        lines.append(f"| **상태** | {self._status_badge()} |")
        lines.append(f"| **담당자** | {self.owner or '-'} |")
        lines.append(f"| **마감일** | {self.due_date or '-'} |")
        lines.append(f"| **우선순위** | {self._priority_badge()} |")
        lines.append(f"| **카테고리** | {self.category} |")
        lines.append(f"| **위치(Zone)** | {self.zone or '-'} |")
        lines.append(f"| **발생원** | {self.source_origin or '-'} |")
        lines.append("")

        # 설명
        lines.append("## 📝 설명")
        lines.append("")
        if self.description:
            lines.append(self.description)
        else:
            lines.append("_설명이 없습니다._")
        lines.append("")

        # 조치계획 / 결정사항
        if self.action_plan or self.decision:
            lines.append("## 📌 조치 및 결정")
            lines.append("")
            lines.append(f"- **조치계획**: {self.action_plan or '-'}")
            lines.append(f"- **결정사항**: {self.decision or '-'}")
            lines.append("")

        # 관련 문서
        if self.related_docs:
            lines.append("## 🔗 관련 문서")
            lines.append("")
            for doc in self.related_docs:
                lines.append(f"- [[{doc}]]")
            lines.append("")

        # 히스토리
        lines.append("## 📅 히스토리")
        lines.append("")
        lines.append(f"- 생성: {self.created_at or '-'}")
        lines.append(f"- 수정: {self.updated_at or '-'}")
        lines.append(f"- 동기화: {self.last_synced_at}")
        lines.append("")

        return "\n".join(lines)

    def _status_badge(self) -> str:
        badges = {
            "open": "🔴 열림",
            "in_progress": "🟡 진행중",
            "resolved": "🟢 완료",
            "closed": "⚫ 종료",
            "on_hold": "⏸️ 보류",
        }
        return badges.get(self.issue_status, self.issue_status)

    def _priority_badge(self) -> str:
        badges = {
            "critical": "🔥 긴급",
            "high": "🔴 높음",
            "medium": "🟡 중간",
            "low": "🟢 낮음",
        }
        return badges.get(self.priority, self.priority)


@dataclass
class SyncResult:
    """동기화 결과"""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: List[str] = field(default_factory=list)


# ─── Google Sheets Client ───────────────────────────────────
class GoogleSheetsClient:
    """Google Sheets API 클라이언트"""

    def __init__(self, credentials_path: Path):
        self.credentials_path = credentials_path
        self._client = None
        self._sheet = None

    def connect(self, spreadsheet_id: str, sheet_name: str) -> bool:
        """Google Sheets에 연결"""
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError:
            log.error("gspread 패키지가 필요합니다. pip install gspread google-auth")
            return False

        if not self.credentials_path.exists():
            log.error(f"인증 파일이 없습니다: {self.credentials_path}")
            log.info("'python p5_issue_sync.py setup' 명령으로 설정 안내를 확인하세요.")
            return False

        try:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(
                str(self.credentials_path), scopes=scopes
            )
            self._client = gspread.authorize(creds)
            spreadsheet = self._client.open_by_key(spreadsheet_id)
            self._sheet = spreadsheet.worksheet(sheet_name)
            log.info(f"Google Sheets 연결 성공: {spreadsheet.title} / {sheet_name}")
            return True
        except Exception as e:
            log.error(f"Google Sheets 연결 실패: {e}")
            return False

    def push_updates(self, updates: List[Dict[str, str]]) -> int:
        """Vault 변경사항 → Sheets 반영 (비어있는 셀만, batch 방식)

        Args:
            updates: [{"issue_id": "SEN-070", "field": "담당자", "value": "이동혁"}]

        Returns:
            반영 건수
        """
        if not self._sheet:
            log.error("먼저 connect()를 호출하세요")
            return 0

        try:
            all_data = self._sheet.get_all_values()
            if not all_data:
                log.warning("시트에 데이터가 없습니다")
                return 0

            headers = all_data[0]

            # NO 컬럼으로 행 인덱스 맵 구축 (1회만)
            no_col_idx = headers.index("NO") if "NO" in headers else 0
            row_map = {}  # issue_id → row_number (1-based)
            for row_idx, row in enumerate(all_data[1:], start=2):
                if no_col_idx < len(row) and row[no_col_idx]:
                    row_map[row[no_col_idx]] = row_idx

            # batch용 셀 목록 수집
            cells_to_update = []
            skipped_existing = 0
            skipped_notfound = 0

            for update in updates:
                issue_id = update["issue_id"]
                field_name = update["field"]
                value = update["value"]

                if field_name not in headers:
                    continue
                col_idx = headers.index(field_name) + 1  # gspread는 1-based

                target_row = row_map.get(issue_id)
                if not target_row:
                    skipped_notfound += 1
                    continue

                # 기존 값 확인 (비어있을 때만 쓰기)
                current_val = ""
                if target_row - 1 < len(all_data) and col_idx - 1 < len(
                    all_data[target_row - 1]
                ):
                    current_val = all_data[target_row - 1][col_idx - 1].strip()
                if current_val:
                    skipped_existing += 1
                    continue

                cells_to_update.append(
                    {
                        "row": target_row,
                        "col": col_idx,
                        "value": value,
                        "issue_id": issue_id,
                        "field": field_name,
                    }
                )

            if not cells_to_update:
                log.info(
                    f"  반영 대상 없음 (기존값 {skipped_existing}건, 미발견 {skipped_notfound}건)"
                )
                return 0

            # batch_update 사용 (API 콜 1회)
            import gspread.utils

            batch_cells = []
            for c in cells_to_update:
                label = gspread.utils.rowcol_to_a1(c["row"], c["col"])
                batch_cells.append({"range": label, "values": [[c["value"]]]})

            self._sheet.batch_update(batch_cells)
            for c in cells_to_update:
                log.info(f"  ✅ {c['issue_id']}.{c['field']} = {c['value'][:30]}")

            log.info(
                f"  반영 {len(cells_to_update)}건 (기존값 {skipped_existing}건 스킵, 미발견 {skipped_notfound}건 스킵)"
            )
            return len(cells_to_update)
        except Exception as e:
            log.error(f"Sheets push 실패: {e}")
            return 0

    def fetch_all_issues(self) -> List[Dict[str, Any]]:
        """모든 이슈 데이터 가져오기"""
        if not self._sheet:
            log.error("먼저 connect()를 호출하세요")
            return []

        try:
            records = self._sheet.get_all_records()
            log.info(f"{len(records)}개 이슈 로드 완료")
            return records
        except Exception as e:
            log.error(f"데이터 로드 실패: {e}")
            return []

    def append_to_issue(
        self, issue_id: str, field: str, value: str, separator: str = ", "
    ) -> bool:
        """특정 이슈의 필드에 값 추가 (중복 방지)"""
        if not self._sheet:
            log.error("먼저 connect()를 호출하세요")
            return False

        try:
            # 1. 헤더에서 컬럼 인덱스 찾기
            headers = self._sheet.row_values(1)
            if field not in headers:
                log.error(f"컬럼을 찾을 수 없습니다: {field}")
                return False
            col_idx = headers.index(field) + 1

            # 2. Issue ID로 행 찾기
            cell = self._sheet.find(issue_id, in_column=1)  # NO 컬럼 가정
            if not cell:
                log.warning(f"이슈를 찾을 수 없습니다: {issue_id}")
                return False

            row_idx = cell.row

            # 3. 현재 값 읽기
            current_val = self._sheet.cell(row_idx, col_idx).value or ""

            # 4. 중복 확인 및 병합
            # 이미 포함되어 있으면 스킵 (단순 부분 문자열 체크)
            if value in current_val:
                log.info(f"  이미 포함됨: {issue_id}.{field} -> {value}")
                return True

            new_val = f"{current_val}{separator}{value}" if current_val else value

            # 5. 업데이트
            self._sheet.update_cell(row_idx, col_idx, new_val)
            log.info(f"  ✅ 추가 완료: {issue_id}.{field} += {value}")
            return True

        except Exception as e:
            log.error(f"값 추가 실패 ({issue_id}): {e}")
            return False

    def update_context_sheet(
        self, content: str, sheet_name: str = "NotebookLM_Source"
    ) -> bool:
        """NotebookLM용 지식 데이터(Context) 시트 생성 및 갱신"""
        if not self._client:
            log.error("먼저 connect()를 호출하세요")
            return False

        try:
            # 시트 열기 또는 생성
            spreadsheet = self._sheet.spreadsheet
            try:
                ws = spreadsheet.worksheet(sheet_name)
            except Exception:
                log.info(f"'{sheet_name}' 시트 생성 중...")
                ws = spreadsheet.add_worksheet(title=sheet_name, rows=100, cols=5)

            # 내용 클리어 및 업데이트
            ws.clear()

            # 긴 텍스트를 여러 셀에 나누어 기록 (셀당 글자수 제한 회피)
            # A1 셀에 메타데이터, A2 셀부터 내용
            today = datetime.now().strftime("%Y-%m-%d %H:%M")
            ws.update_acell("A1", f"Project Summary (Refreshed: {today})")

            # 청크 단위로 분할하여 기록 (약 4000자씩)
            chunks = [content[i : i + 4000] for i in range(0, len(content), 4000)]

            cells = []
            for i, chunk in enumerate(chunks, start=2):
                cells.append({"range": f"A{i}", "values": [[chunk]]})

            ws.batch_update(cells)
            log.info(f"✅ Context 업데이트 완료: {sheet_name} ({len(content)} chars)")
            return True

        except Exception as e:
            log.error(f"Context 시트 업데이트 실패: {e}")
            return False


# ─── CSV Fallback ───────────────────────────────────────────
def load_from_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """CSV 파일에서 이슈 로드 (fallback)"""
    try:
        import pandas as pd
    except ImportError:
        log.error("pandas 패키지가 필요합니다. pip install pandas")
        return []

    if not csv_path.exists():
        log.error(f"CSV 파일이 없습니다: {csv_path}")
        return []

    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        records = df.to_dict("records")
        log.info(f"CSV에서 {len(records)}개 이슈 로드 완료")
        return records
    except Exception as e:
        log.error(f"CSV 로드 실패: {e}")
        return []


# ─── Context Generation ─────────────────────────────────────
def generate_project_context(records: List[Dict[str, Any]]) -> str:
    """이슈 리스트를 분석하여 LLM용 컨텍스트(요약본) 생성"""
    lines = []
    today = datetime.now().strftime("%Y-%m-%d")

    lines.append(f"# P5 복합동 프로젝트 현황 리포트 ({today})")
    lines.append("본 문서는 프로젝트의 최신 이슈와 결정사항을 요약한 것입니다.")
    lines.append("")

    # 1. 통계
    total = len(records)
    open_issues = sum(1 for r in records if r.get("상태", "") in ["열림", "진행중"])
    critical = sum(
        1
        for r in records
        if r.get("긴급도", "") in ["긴급", "높음"] and r.get("상태", "") != "완료"
    )

    lines.append("## 1. 개요")
    lines.append(f"- 전체 이슈: {total}건")
    lines.append(f"- 진행중/열림: {open_issues}건")
    lines.append(f"- 긴급/높음(미결): {critical}건")
    lines.append("")

    # 2. 우선순위 높은 미결 이슈 (Top 30)
    lines.append("## 2. 주요 미결 하안 (High Priority)")
    lines.append("| NO | 이슈명 | 담당자 | 마감일 | 현황 |")
    lines.append("|---|---|---|---|---|")

    # Priority sort: 긴급 > 높음 > 중간 > 낮음
    priority_order = {"긴급": 0, "높음": 1, "중간": 2, "낮음": 3}

    active_issues = [
        r for r in records if r.get("상태", "") not in ["완료", "종료", "보류"]
    ]
    active_issues.sort(key=lambda x: priority_order.get(x.get("긴급도", "중간"), 99))

    for r in active_issues[:30]:
        lines.append(
            f"| {r.get('NO')} | {r.get('이슈명')} | {r.get('담당자')} | {r.get('마감일')} | {r.get('상세내용(Spec)', '')[:50]}... |"
        )

    lines.append("")

    # 3. 최근 결정사항 (Recent Decisions) - 최근 2주? (데이터에 날짜가 명확치 않으므로, 결정사항이 있는 것 위주로)
    lines.append("## 3. 주요 결정사항 (Decisions)")
    decided_issues = [r for r in records if r.get("결정사항", "").strip()]
    # 역순 (최신 번호)
    decided_issues.sort(key=lambda x: str(x.get("NO", "")), reverse=True)

    for r in decided_issues[:20]:
        lines.append(f"- **{r.get('NO')} {r.get('이슈명')}**: {r.get('결정사항')}")

    lines.append("")

    # 4. 오늘의 일정 (Notion 등에서 가져오면 좋지만, 일단 이슈 마감일 기준)
    lines.append("## 4. 금주 마감 예정 이슈")
    # 마감일 파싱 로직은 복잡하므로 생략하거나 문자열 매칭 정도만 수행
    # (여기서는 생략)

    return "\n".join(lines)


# ─── Issue Sync Logic ───────────────────────────────────────
def parse_issue(
    record: Dict[str, Any], config: Optional[dict] = None
) -> Optional[Issue]:
    """레코드를 Issue 객체로 파싱"""
    try:
        # 설정 파일에서 매핑 가져오기, 없으면 기본값 사용
        column_mapping = (
            config.get("column_mapping", COLUMN_MAPPING) if config else COLUMN_MAPPING
        )
        status_mapping = (
            config.get("status_mapping", STATUS_MAPPING) if config else STATUS_MAPPING
        )
        priority_mapping = (
            config.get("priority_mapping", PRIORITY_MAPPING)
            if config
            else PRIORITY_MAPPING
        )

        # 컬럼 매핑 적용
        mapped = {}
        for kr_col, en_col in column_mapping.items():
            if kr_col in record:
                mapped[en_col] = record[kr_col]
            elif en_col in record:
                mapped[en_col] = record[en_col]

        # 필수 필드 확인
        issue_id = str(mapped.get("issue_id", "")).strip()
        title = str(mapped.get("title", "")).strip()

        if not issue_id or not title:
            return None

        # 상태/우선순위/카테고리 매핑
        raw_status = str(mapped.get("issue_status", "열림"))
        raw_priority = str(mapped.get("priority", "중간"))
        raw_category = str(mapped.get("category", "일반"))

        issue_status = status_mapping.get(raw_status, raw_status.lower())
        priority = priority_mapping.get(raw_priority, raw_priority.lower())
        category = CATEGORY_MAPPING.get(raw_category, raw_category.lower())

        # 날짜 처리
        due_date = str(mapped.get("due_date", "")).strip()
        created_at = str(mapped.get("created_at", "")).strip()
        updated_at = str(mapped.get("updated_at", "")).strip()

        # 관련 문서 파싱 (쉼표 구분)
        related_raw = str(mapped.get("related_docs", ""))
        related_docs = [d.strip() for d in related_raw.split(",") if d.strip()]

        return Issue(
            issue_id=issue_id,
            title=title,
            issue_status=issue_status,
            owner=str(mapped.get("owner", "")).strip(),
            due_date=due_date,
            priority=priority,
            category=category,
            description=str(mapped.get("description", "")).strip(),
            related_docs=related_docs,
            created_at=created_at,
            updated_at=updated_at,
            last_synced_at=datetime.now().isoformat(),
            zone=str(mapped.get("zone", "")).strip(),
            source_origin=str(mapped.get("source_origin", "")).strip(),
            action_plan=str(mapped.get("action_plan", "")).strip(),
            decision=str(mapped.get("decision", "")).strip(),
        )
    except Exception as e:
        log.warning(f"이슈 파싱 실패: {e}")
        return None


def upsert_issue(issue: Issue, output_dir: Path) -> tuple[Path, str]:
    """
    이슈를 마크다운 파일로 저장/갱신 (upsert)

    Returns:
        (파일경로, 상태) - 상태: "created" | "updated" | "unchanged"
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 파일명: {issue_id}-{safe_title}.md
    safe_title = "".join(
        c for c in issue.title if c.isalnum() or c in " -_가-힣"
    ).strip()
    safe_title = safe_title.replace(" ", "-")[:50]
    filename = f"{issue.issue_id}-{safe_title}.md"
    filepath = output_dir / filename

    # 기존 파일 확인
    existing_files = list(output_dir.glob(f"{issue.issue_id}-*.md"))

    new_content = issue.to_markdown()

    if existing_files:
        # 기존 파일이 있으면 업데이트
        old_file = existing_files[0]
        try:
            old_content = old_file.read_text(encoding="utf-8")

            # 내용 비교 (동기화 시간 제외)
            def strip_sync_time(content: str) -> str:
                lines = content.split("\n")
                return "\n".join(
                    l
                    for l in lines
                    if not l.startswith("last_synced_at:")
                    and not l.startswith("- 동기화:")
                )

            if strip_sync_time(old_content) == strip_sync_time(new_content):
                return old_file, "unchanged"

            # 파일명이 다르면 이전 파일 삭제
            if old_file != filepath:
                old_file.unlink()

            filepath.write_text(new_content, encoding="utf-8")
            return filepath, "updated"
        except Exception:
            pass

    # 새 파일 생성
    filepath.write_text(new_content, encoding="utf-8")
    return filepath, "created"


def sync_issues(
    records: List[Dict[str, Any]],
    output_dir: Path,
    config: Optional[dict] = None,
) -> SyncResult:
    """이슈 목록을 Vault에 동기화"""
    result = SyncResult()

    for record in records:
        issue = parse_issue(record, config)
        if not issue:
            result.errors.append(f"파싱 실패: {record.get('NO', 'unknown')}")
            continue

        try:
            filepath, status = upsert_issue(issue, output_dir)

            if status == "created":
                result.created += 1
                log.info(f"✅ 생성: {filepath.name}")
            elif status == "updated":
                result.updated += 1
                log.info(f"🔄 갱신: {filepath.name}")
            else:
                result.unchanged += 1
                log.debug(f"⏭️ 변경없음: {filepath.name}")

        except Exception as e:
            result.errors.append(f"{issue.issue_id}: {e}")
            log.error(f"❌ 저장 실패 ({issue.issue_id}): {e}")

    return result


# ─── Commands ───────────────────────────────────────────────
def cmd_sync(args):
    """동기화 실행"""
    log.info("=" * 50)
    log.info("P5 이슈 동기화 시작")
    log.info("=" * 50)

    records = []

    if args.csv:
        # CSV fallback
        csv_path = Path(args.csv)
        records = load_from_csv(csv_path)
        source = f"CSV: {csv_path}"
    else:
        # Google Sheets API
        config = load_config()
        spreadsheet_id = config.get("spreadsheet_id", DEFAULT_SPREADSHEET_ID)
        sheet_name = config.get("sheet_name", DEFAULT_SHEET_NAME)

        if not spreadsheet_id:
            log.error("spreadsheet_id가 설정되지 않았습니다.")
            log.info("설정 파일을 확인하거나 --csv 옵션을 사용하세요.")
            return

        client = GoogleSheetsClient(CREDENTIALS_PATH)
        if not client.connect(spreadsheet_id, sheet_name):
            return

        records = client.fetch_all_issues()
        source = f"Google Sheets: {sheet_name}"

    if not records:
        log.warning("동기화할 이슈가 없습니다.")
        return

    log.info(f"소스: {source}")
    log.info(f"대상: {ISSUES_DIR}")

    config = load_config()
    result = sync_issues(records, ISSUES_DIR, config)

    log.info("")
    log.info("=" * 50)
    log.info("동기화 완료!")
    log.info(f"  생성: {result.created}개")
    log.info(f"  갱신: {result.updated}개")
    log.info(f"  변경없음: {result.unchanged}개")
    if result.errors:
        log.warning(f"  오류: {len(result.errors)}개")
        for err in result.errors[:5]:
            log.warning(f"    - {err}")
    log.info("=" * 50)


def _parse_frontmatter(file_path: Path) -> dict:
    """파일에서 YAML frontmatter를 파싱하여 dict로 반환"""
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def classify_issue_tier(fm: dict, config: dict) -> str:
    """이슈 frontmatter → tier1/tier2/tier3 분류

    Args:
        fm: 이슈 frontmatter dict
        config: p5-sync-config.yaml 전체 dict

    Returns:
        "tier1_active" | "tier2_watch" | "tier3_archive"
    """
    tiered = config.get("tiered_sync", {})
    if not tiered.get("enabled", False):
        return "tier1_active"  # 비활성이면 모두 active

    status = fm.get("issue_status", "open")
    priority = fm.get("priority", "medium")

    # tier3 먼저 체크 (closed/resolved)
    t3 = tiered.get("tier3_archive", {}).get("criteria", {})
    if status in t3.get("status", []):
        return "tier3_archive"

    # tier1 체크
    t1 = tiered.get("tier1_active", {}).get("criteria", {})
    if priority in t1.get("priority", []) and status in t1.get("status", []):
        return "tier1_active"

    # tier2 체크
    t2 = tiered.get("tier2_watch", {}).get("criteria", {})
    if priority in t2.get("priority", []) and status in t2.get("status", []):
        return "tier2_watch"

    # 나머지 (low priority 등)
    return "tier2_watch"


def cmd_status(args):
    """동기화 상태 + 데이터 품질 리포트"""
    print("=" * 60)
    print("P5 이슈 동기화 상태 + 품질 리포트")
    print("=" * 60)

    if not ISSUES_DIR.exists():
        print("\n⚠️ 이슈 디렉토리가 없습니다.")
        return

    issue_files = list(ISSUES_DIR.glob("SEN-*.md"))
    manual_files = [f for f in ISSUES_DIR.glob("*.md") if not f.name.startswith("SEN-")]
    total = len(issue_files) + len(manual_files)
    print(
        f"\n📁 전체 이슈: {total}개 (SEN: {len(issue_files)}, 수동: {len(manual_files)})"
    )

    # frontmatter 전체 파싱
    all_fm = {}
    for f in issue_files:
        all_fm[f.name] = _parse_frontmatter(f)
    for f in manual_files:
        all_fm[f.name] = _parse_frontmatter(f)

    # ── 1. 상태별 집계 ──
    status_count: Dict[str, int] = {}
    priority_count: Dict[str, int] = {}
    for fname, fm in all_fm.items():
        s = fm.get("issue_status", "미지정")
        status_count[s] = status_count.get(s, 0) + 1
        p = fm.get("priority", "미지정")
        priority_count[p] = priority_count.get(p, 0) + 1

    print("\n📊 상태별 현황:")
    for s, c in sorted(status_count.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}개")

    print("\n🔥 긴급도별 현황:")
    for p, c in sorted(priority_count.items(), key=lambda x: -x[1]):
        print(f"  {p}: {c}개")

    # ── 1.5 계층(Tier) 분포 ──
    config = load_config()
    if config.get("tiered_sync", {}).get("enabled", False):
        tier_count: Dict[str, int] = {}
        for fname, fm in all_fm.items():
            tier = classify_issue_tier(fm, config)
            tier_count[tier] = tier_count.get(tier, 0) + 1

        print("\n📐 계층(Tier) 분포:")
        t1 = tier_count.get("tier1_active", 0)
        t2 = tier_count.get("tier2_watch", 0)
        t3 = tier_count.get("tier3_archive", 0)
        print(f"  T1(Active): {t1}개 | T2(Watch): {t2}개 | T3(Archive): {t3}개")

    # ── 2. 데이터 품질 경고 ──
    print("\n" + "─" * 60)
    print("⚠️  데이터 품질 경고")
    print("─" * 60)

    no_owner = []
    no_due_date_hc = []
    no_category = []
    no_zone = []
    no_source_origin = []
    stale_open = []

    for fname, fm in all_fm.items():
        priority = fm.get("priority", "")
        status = fm.get("issue_status", "")

        # 담당자 미지정
        if not fm.get("owner") or fm.get("owner", "").strip() == "":
            no_owner.append((fname, priority))

        # high/critical인데 마감일 없음
        if priority in ("high", "critical", "상") and not fm.get("due_date"):
            no_due_date_hc.append((fname, priority))

        # 카테고리/공법구분 없음
        if not fm.get("category") or fm.get("category", "").strip() == "":
            no_category.append(fname)

        # zone 없음 (빈 문자열 포함)
        if not fm.get("zone") or fm.get("zone", "").strip() == "":
            no_zone.append(fname)

        # source_origin 없음
        if not fm.get("source_origin") or fm.get("source_origin", "").strip() == "":
            no_source_origin.append(fname)

    warnings = 0

    if no_owner:
        warnings += 1
        print(f"\n  🔴 담당자 미지정: {len(no_owner)}건")
        hc_no_owner = [(f, p) for f, p in no_owner if p in ("high", "critical", "상")]
        if hc_no_owner:
            print(f"     (high/critical 중: {len(hc_no_owner)}건 - 즉시 할당 권장)")
            for fname, pri in hc_no_owner[:5]:
                print(f"       - {fname} [{pri}]")

    if no_due_date_hc:
        warnings += 1
        print(f"\n  🔴 마감일 없는 high/critical: {len(no_due_date_hc)}건")
        for fname, pri in no_due_date_hc[:5]:
            print(f"       - {fname} [{pri}]")

    if no_category:
        warnings += 1
        print(f"\n  🟡 카테고리 미지정: {len(no_category)}건")

    if no_zone:
        warnings += 1
        print(f"\n  🟡 위치(Zone) 미지정: {len(no_zone)}건")

    if no_source_origin:
        warnings += 1
        print(f"\n  🟡 발생원 미지정: {len(no_source_origin)}건")

    if warnings == 0:
        print("\n  ✅ 품질 경고 없음")

    # ── 3. 트리아지 현황 ──
    triaged = [f for f, fm in all_fm.items() if fm.get("triage_score")]
    review_queue = ISSUES_DIR.parent / "00-Overview" / "triage-review-queue.md"
    pending_review = 0
    if review_queue.exists():
        content = review_queue.read_text(encoding="utf-8")
        pending_review = content.count("- [ ] **")

    print("\n" + "─" * 60)
    print("🎯 트리아지 현황")
    print("─" * 60)
    print(f"  트리아지 완료: {len(triaged)}건")
    print(f"  리뷰 대기: {pending_review}건")

    # ── 4. 발신조직별 현황 ──
    org_count: Dict[str, int] = {}
    for fname, fm in all_fm.items():
        org = fm.get("source_origin", "").strip()
        if org:
            org_count[org] = org_count.get(org, 0) + 1
    if org_count:
        print("\n🏢 발신조직별 현황:")
        for org, c in sorted(org_count.items(), key=lambda x: -x[1])[:10]:
            print(f"  {org}: {c}건")

    # ── 5. 설정 확인 ──
    print("\n" + "─" * 60)
    print("⚙️  설정")
    print("─" * 60)
    print(f"  인증 파일: {'✅ 있음' if CREDENTIALS_PATH.exists() else '❌ 없음'}")
    config = load_config()
    print(f"  Spreadsheet ID: {config.get('spreadsheet_id', '미설정')[:20]}...")
    print(f"  Sheet Name: {config.get('sheet_name', DEFAULT_SHEET_NAME)}")

    # 마지막 동기화
    if LOG_FILE.exists():
        import os

        mtime = datetime.fromtimestamp(os.path.getmtime(LOG_FILE))
        print(f"\n🕐 마지막 동기화: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")


def cmd_setup(args):
    """API 설정 안내"""
    print(
        """
╔══════════════════════════════════════════════════════════════╗
║           P5 이슈 동기화 - Google Sheets API 설정             ║
╚══════════════════════════════════════════════════════════════╝

📋 설정 단계:

1️⃣ Google Cloud Console에서 프로젝트 생성
   https://console.cloud.google.com/

2️⃣ Google Sheets API & Drive API 활성화
   - APIs & Services > Library 에서 검색 후 Enable

3️⃣ Service Account 생성
   - APIs & Services > Credentials > Create Credentials
   - "Service Account" 선택
   - 이름 입력 후 생성

4️⃣ JSON 키 파일 다운로드
   - Service Account 클릭 > Keys > Add Key > Create new key
   - JSON 선택 후 다운로드
   - 다운로드 된 파일을 다음 경로로 이동:
"""
    )
    print(f"     {CREDENTIALS_PATH}")
    print(
        """
5️⃣ Google Sheet에 Service Account 공유
   - JSON 파일에서 "client_email" 값 복사
   - Google Sheet 열기 > 공유 > 해당 이메일 추가 (Viewer 권한)

6️⃣ 설정 파일 생성
"""
    )
    print(f"   {CONFIG_PATH}")
    print(
        """
   내용:
   ```yaml
   spreadsheet_id: "YOUR_SPREADSHEET_ID"  # Google Sheet URL에서 /d/ 뒤의 ID
   sheet_name: "이슈목록"                  # 시트 탭 이름
   ```

7️⃣ 동기화 테스트
   python p5_issue_sync.py sync

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 CSV fallback 사용 시:
   python p5_issue_sync.py sync --csv "경로/issues.csv"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    )


def load_config() -> dict:
    """설정 파일 로드"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


# ─── Main ───────────────────────────────────────────────────
def cmd_push(args):
    """Vault → Sheets 역동기화"""
    log.info("=" * 50)
    log.info("Vault → Google Sheets 역동기화")
    log.info("=" * 50)

    dry_run = getattr(args, "dry_run", False)

    # reverse_sync 설정 로드
    config = _load_config()
    reverse_cfg = config.get("reverse_sync", {})
    if not reverse_cfg.get("enabled", True):
        log.info("reverse_sync가 비활성화되어 있습니다.")
        return

    only_fill_empty = reverse_cfg.get("only_fill_empty", True)
    rev_mapping = reverse_cfg.get(
        "reverse_column_mapping",
        {
            "owner": "담당자",
            "due_date": "마감일",
            "issue_status": "상태",
            "decision": "결정사항",
        },
    )
    target_fields = reverse_cfg.get(
        "fields", ["owner", "due_date", "issue_status", "decision"]
    )

    # 역매핑: 영문→한글 (Sheets 컬럼명)
    STATUS_REVERSE = {v: k for k, v in STATUS_MAPPING.items()}

    # SEN 이슈 파일 스캔
    updates = []
    if not ISSUES_DIR.exists():
        log.warning("이슈 디렉토리 없음")
        return

    for f in ISSUES_DIR.glob("SEN-*.md"):
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            if not content.startswith("---"):
                continue
            parts = content.split("---", 2)
            if len(parts) < 3:
                continue
            fm = yaml.safe_load(parts[1]) or {}
            issue_id = fm.get("issue_id", "")
            if not issue_id:
                continue

            for en_field in target_fields:
                if en_field not in rev_mapping:
                    continue
                val = str(fm.get(en_field, "")).strip()
                if not val:
                    continue
                # suggested_ 필드는 push하지 않음
                if en_field.startswith("suggested_"):
                    continue

                kr_col = rev_mapping[en_field]

                # 상태는 역매핑 (영문→한글)
                if en_field == "issue_status" and val in STATUS_REVERSE:
                    val = STATUS_REVERSE[val]

                updates.append(
                    {
                        "issue_id": issue_id,
                        "field": kr_col,
                        "value": val,
                    }
                )
        except Exception:
            continue

    # 필드별 집계
    field_counts = {}
    for u in updates:
        field_counts[u["field"]] = field_counts.get(u["field"], 0) + 1
    log.info(f"역동기화 후보: {len(updates)}건")
    for fname, cnt in sorted(field_counts.items(), key=lambda x: -x[1]):
        log.info(f"  - {fname}: {cnt}건")

    if dry_run:
        # 상태 외 실질적 변경만 상세 표시
        non_status = [u for u in updates if u["field"] != "상태"]
        if non_status:
            log.info(f"[DRY-RUN] 상태 외 변경 ({len(non_status)}건):")
            for u in non_status[:20]:
                log.info(f"  {u['issue_id']}.{u['field']} = {u['value'][:30]}")
            if len(non_status) > 20:
                log.info(f"  ... 외 {len(non_status) - 20}건")
        else:
            log.info("[DRY-RUN] 상태 필드만 존재 (Sheets에 이미 있으면 스킵됨)")
        log.info("실제 반영 시 Sheets에서 비어있는 셀만 업데이트됩니다.")
        return

    if not updates:
        log.info("역동기화할 항목 없음")
        return

    # Google Sheets 연결 + push
    client = GoogleSheetsClient(CREDENTIALS_PATH)
    config_data = _load_config()
    ss_id = config_data.get("spreadsheet_id", DEFAULT_SPREADSHEET_ID)
    sheet_name = config_data.get("sheet_name", DEFAULT_SHEET_NAME)

    if not client.connect(ss_id, sheet_name):
        log.error("Google Sheets 연결 실패")
        return

    pushed = client.push_updates(updates)
    log.info(f"✅ 역동기화 완료: {pushed}/{len(updates)}건 반영")


def _load_ingest_policy() -> dict:
    """ingest-policy.yaml에서 issue_lifecycle 설정 로드"""
    policy_path = VAULT_PATH / "_config" / "ingest-policy.yaml"
    defaults = {
        "fresh_days": 14,
        "triage_fresh_days": 30,
        "aging_days": 30,
        "stale_days": 60,
        "dormant_days": 90,
        "aging_downgrade_from": ["high"],
        "aging_downgrade_to": "medium",
    }
    if not policy_path.exists():
        return defaults
    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        lc = data.get("issue_lifecycle", {})
        return {**defaults, **lc}
    except Exception:
        return defaults


def _parse_date(raw: str) -> Optional[datetime]:
    """다양한 날짜 형식 파싱 (ISO, 한글 AM/PM 등)"""
    import re

    raw = str(raw).strip().strip("'\"")
    if not raw:
        return None
    # ISO format with optional microseconds
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    # Korean format: "2025. 11. 19 오전 9:58:23" or "2025. 11. 19 오후 3:44:57"
    m = re.match(
        r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\s*(오전|오후)\s*(\d{1,2}):(\d{2}):(\d{2})",
        raw,
    )
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ampm, hour, minute, second = (
            m.group(4),
            int(m.group(5)),
            int(m.group(6)),
            int(m.group(7)),
        )
        if ampm == "오후" and hour < 12:
            hour += 12
        elif ampm == "오전" and hour == 12:
            hour = 0
        return datetime(year, month, day, hour, minute, second)
    return None


def _activity_date(fm: dict) -> Optional[datetime]:
    """frontmatter에서 가장 최근 활동일 반환 (last_triage_at vs created_at)"""
    candidates = []
    for field in ("last_triage_at", "created_at"):
        dt = _parse_date(fm.get(field, ""))
        if dt:
            candidates.append(dt)
    return max(candidates) if candidates else None


def _classify_freshness(age_days: int, priority: str, lc: dict, fm: dict = None) -> str:
    """활동 경과일 → freshness 등급 반환

    Fresh: last_triage_at 30일 이내 OR created_at 14일 이내
    Aging: 30~60일 + priority in aging_downgrade_from
    Stale: 60~90일
    Dormant: 90일+
    """
    # created_at 14일 이내면 무조건 fresh
    if fm:
        created_dt = _parse_date(fm.get("created_at", ""))
        if created_dt:
            created_age = (datetime.now() - created_dt).days
            if created_age <= lc["fresh_days"]:
                return "fresh"

    # activity_date 기준 (max of last_triage_at, created_at)
    if age_days <= lc["triage_fresh_days"]:
        return "fresh"
    if age_days <= lc["stale_days"]:
        if priority in lc["aging_downgrade_from"]:
            return "aging"
        return "fresh"
    if age_days <= lc["dormant_days"]:
        return "stale"
    return "dormant"


def _update_frontmatter(file_path: Path, updates: dict) -> bool:
    """frontmatter 필드 업데이트 (기존 내용 보존)"""
    try:
        content = file_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return False
        parts = content.split("---", 2)
        if len(parts) < 3:
            return False
        fm = yaml.safe_load(parts[1]) or {}
        fm.update(updates)
        # tags 업데이트 (status/priority 태그 반영)
        if "tags" in fm and isinstance(fm["tags"], list):
            new_tags = []
            for tag in fm["tags"]:
                if tag.startswith("status/") and "issue_status" in updates:
                    new_tags.append(f"status/{updates['issue_status']}")
                elif tag.startswith("priority/") and "priority" in updates:
                    new_tags.append(f"priority/{updates['priority']}")
                else:
                    new_tags.append(tag)
            fm["tags"] = new_tags
        new_fm = yaml.dump(
            fm, allow_unicode=True, default_flow_style=False, sort_keys=False
        ).rstrip()
        new_content = f"---\n{new_fm}\n---{parts[2]}"
        file_path.write_text(new_content, encoding="utf-8")
        return True
    except Exception as e:
        log.error(f"frontmatter 업데이트 실패 ({file_path.name}): {e}")
        return False


def cmd_archive(args):
    """이슈 수명주기 관리 - freshness 기반 상태 전이"""
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)

    log.info("=" * 60)
    log.info("이슈 수명주기 관리 (Freshness-based Archive)")
    log.info("=" * 60)

    if dry_run:
        log.info("[DRY-RUN] 실제 변경 없이 분석만 수행합니다.")

    # 정책 로드
    lc = _load_ingest_policy()
    log.info(
        f"정책: fresh={lc['fresh_days']}d, triage_fresh={lc['triage_fresh_days']}d, "
        f"aging={lc['aging_days']}d, stale={lc['stale_days']}d, dormant={lc['dormant_days']}d"
    )

    if not ISSUES_DIR.exists():
        log.error(f"이슈 디렉토리 없음: {ISSUES_DIR}")
        return

    issue_files = list(ISSUES_DIR.glob("SEN-*.md"))
    log.info(f"스캔 대상: {len(issue_files)}개 이슈")

    now = datetime.now()

    # 등급별 집계
    tiers = {"fresh": [], "aging": [], "stale": [], "dormant": [], "no_date": []}
    stats = {"aging_applied": 0, "stale_applied": 0, "dormant_applied": 0, "errors": 0}

    for f in issue_files:
        fm = _parse_frontmatter(f)
        if not fm:
            continue

        issue_id = fm.get("issue_id", f.stem)
        status = fm.get("issue_status", "open")
        priority = fm.get("priority", "medium")

        # 이미 전이된 이슈 → 스킵
        if status in ("resolved", "closed", "on_hold"):
            continue

        act_date = _activity_date(fm)
        if not act_date:
            tiers["no_date"].append(f.name)
            continue

        age_days = (now - act_date).days
        tier = _classify_freshness(age_days, priority, lc, fm=fm)
        tiers[tier].append(f.name)

        if dry_run:
            continue

        # 실제 적용
        if tier == "aging" and priority in lc["aging_downgrade_from"]:
            ok = _update_frontmatter(
                f,
                {
                    "priority": lc["aging_downgrade_to"],
                    "previous_priority": priority,
                },
            )
            if ok:
                stats["aging_applied"] += 1
                log.info(
                    f"  [Aging] {issue_id}: priority {priority}→{lc['aging_downgrade_to']} (age={age_days}d)"
                )
            else:
                stats["errors"] += 1

        elif tier == "stale":
            ok = _update_frontmatter(
                f,
                {
                    "issue_status": "on_hold",
                    "previous_status": status,
                },
            )
            if ok:
                stats["stale_applied"] += 1
                log.info(
                    f"  [Stale] {issue_id}: status {status}→on_hold (age={age_days}d)"
                )
            else:
                stats["errors"] += 1

        elif tier == "dormant":
            ok = _update_frontmatter(
                f,
                {
                    "issue_status": "resolved",
                    "previous_status": status,
                    "archived_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
            if ok:
                stats["dormant_applied"] += 1
                log.info(
                    f"  [Dormant] {issue_id}: status {status}→resolved (age={age_days}d)"
                )
            else:
                stats["errors"] += 1

    # 결과 리포트
    print()
    print("=" * 60)
    print("Freshness 분석 결과")
    print("=" * 60)
    print(f"  Fresh   (유지):       {len(tiers['fresh'])}건")
    print(f"  Aging   (priority↓):  {len(tiers['aging'])}건")
    print(f"  Stale   (→on_hold):   {len(tiers['stale'])}건")
    print(f"  Dormant (→resolved):  {len(tiers['dormant'])}건")
    print(f"  날짜없음:              {len(tiers['no_date'])}건")
    print()

    if dry_run:
        print("[DRY-RUN] 실제 적용하려면: python p5_issue_sync.py archive")
    else:
        print("적용 결과:")
        print(f"  Aging 다운그레이드: {stats['aging_applied']}건")
        print(f"  Stale → on_hold:    {stats['stale_applied']}건")
        print(f"  Dormant → resolved: {stats['dormant_applied']}건")
        if stats["errors"]:
            print(f"  오류: {stats['errors']}건")
        total_applied = (
            stats["aging_applied"] + stats["stale_applied"] + stats["dormant_applied"]
        )
        log.info(
            f"[archive] Aging:{stats['aging_applied']}건, Stale:{stats['stale_applied']}건, Dormant:{stats['dormant_applied']}건"
        )


def cmd_context(args):
    """Context 업데이트 실행"""
    log.info("=" * 50)
    log.info("NotebookLM Context 업데이트 시작")
    log.info("=" * 50)

    # 설정 로드
    if not CONFIG_PATH.exists():
        log.error(f"설정 파일 없음: {CONFIG_PATH}")
        return

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    spreadsheet_id = config.get("spreadsheet_id", "")
    sheet_name = config.get("sheet_name", "접수 메일")

    if not spreadsheet_id:
        log.error("Spreadsheet ID가 설정되지 않았습니다.")
        return

    # Sheets 연결
    client = GoogleSheetsClient(CREDENTIALS_PATH)
    if not client.connect(spreadsheet_id, sheet_name):
        return

    # 데이터 로드
    records = client.fetch_all_issues()
    if not records:
        log.info("업데이트할 데이터가 없습니다.")
        return

    # Context 생성
    context_text = generate_project_context(records)

    # Context 시트 업데이트
    if client.update_context_sheet(context_text, "NotebookLM_Source"):
        log.info("✅ Context 업데이트 성공")
    else:
        log.error("❌ Context 업데이트 실패")


def _load_config() -> dict:
    """p5-sync-config.yaml 로드"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="P5 이슈 동기화 - Google Sheets ↔ Obsidian Vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", help="명령어")

    # sync
    p_sync = sub.add_parser("sync", help="이슈 동기화 실행")
    p_sync.add_argument("--csv", help="CSV 파일 경로 (API 대신 사용)")
    p_sync.add_argument("--debug", action="store_true", help="디버그 로깅")
    p_sync.set_defaults(func=cmd_sync)

    # push
    p_push = sub.add_parser("push", help="Vault → Sheets 역동기화")
    p_push.add_argument("--dry-run", action="store_true", help="변경 없이 미리보기")
    p_push.set_defaults(func=cmd_push)

    # archive
    p_archive = sub.add_parser("archive", help="이슈 수명주기 관리 (freshness 기반)")
    p_archive.add_argument(
        "--dry-run", action="store_true", help="변경 없이 분석만 수행"
    )
    p_archive.add_argument("--force", action="store_true", help="확인 없이 강제 적용")
    p_archive.set_defaults(func=cmd_archive)

    # status
    p_status = sub.add_parser("status", help="동기화 상태 확인")
    p_status.set_defaults(func=cmd_status)

    # setup
    p_setup = sub.add_parser("setup", help="API 설정 안내")
    p_setup.set_defaults(func=cmd_setup)

    # context (New)
    p_context = sub.add_parser("context", help="NotebookLM용 Context 시트 업데이트")
    p_context.set_defaults(func=cmd_context)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if getattr(args, "debug", False):
        global log
        log = setup_logging(debug=True)

    args.func(args)


if __name__ == "__main__":
    main()
