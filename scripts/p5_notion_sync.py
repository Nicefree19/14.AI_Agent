"""
P5 Notion 동기화 스크립트
Google Sheets ↔ Notion 양방향 동기화

Usage:
    python p5_notion_sync.py sync             # Google Sheets → Notion 동기화
    python p5_notion_sync.py push             # Notion → Google Sheets 역동기화
    python p5_notion_sync.py status           # 동기화 상태 확인
"""

import sys
import io
import os
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# Windows cp949 인코딩 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
import yaml

# ─── Configuration ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"
CONFIG_PATH = PROJECT_ROOT / "ResearchVault" / "_config" / "p5-sync-config.yaml"
CREDENTIALS_PATH = PROJECT_ROOT / ".secrets" / "google-sheets-credentials.json"
LOG_FILE = SCRIPT_DIR / "p5_notion_sync.log"

load_dotenv(ENV_PATH)

NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")

# ─── Notion ↔ Google Sheets 컬럼 매핑 ──────────────────────
# Notion property name → Google Sheets column name
NOTION_TO_SHEETS_MAP = {
    "이슈명": "이슈명",  # title → text
    "NO": "NO",  # rich_text → text
    "상태": "상태",  # select → text
    "담당자": "담당자",  # rich_text → text
    "긴급도": "긴급도",  # select → text
    "공법구분": "공법구분",  # select → text
    "위치": "위치(Zone)",  # rich_text → text
    "상세내용": "상세내용(Spec)",  # rich_text → text
    "관련도면": "관련도면",  # rich_text → text
    "수신일": "수신일",  # date → text
    "마감일": "마감일",  # date → text
    "발생원": "발생원",  # select → text
    "조치계획": "조치계획",  # rich_text → text
    "결정사항": "결정사항",  # rich_text → text
    "카테고리": "카테고리",  # select → text
    "협의대상": "협의대상",  # rich_text → text
    "키워드": "키워드",  # rich_text → text
    "비고": "비고",  # rich_text → text
}

# Notion property types (retrieved from DB schema)
NOTION_PROP_TYPES = {
    "이슈명": "title",
    "NO": "rich_text",
    "상태": "select",
    "담당자": "rich_text",
    "긴급도": "select",
    "공법구분": "select",
    "위치": "rich_text",
    "상세내용": "rich_text",
    "관련도면": "rich_text",
    "수신일": "date",
    "마감일": "date",
    "발생원": "select",
    "조치계획": "rich_text",
    "결정사항": "rich_text",
    "카테고리": "select",
    "협의대상": "rich_text",
    "키워드": "rich_text",
    "비고": "rich_text",
    "영향도": "select",
    "우선순위": "select",
    "접합유형": "select",
    "담당": "select",
    "제작SHOP영향": "select",
    "설계영향": "select",
    "시공현장영향": "select",
    "기술적원인": "rich_text",
    "메시지ID": "rich_text",
    "RawJSON": "rich_text",
    "메일링크": "url",
    "기한": "date",
}


# ─── Logging ────────────────────────────────────────────────
def setup_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("p5_notion_sync")


log = setup_logging()


# ─── Notion Client Wrapper ──────────────────────────────────
class NotionSync:
    """Notion API 동기화 클라이언트"""

    def __init__(self, api_key: str, database_id: str):
        from notion_client import Client

        self.notion = Client(auth=api_key)
        self.database_id = database_id
        self._page_cache: Dict[str, str] = {}  # NO → page_id

    def _format_uuid(self, uuid_str: str) -> str:
        """UUID 문자열에 하이픈 추가 (32자 → 36자)"""
        if len(uuid_str) == 32:
            return f"{uuid_str[:8]}-{uuid_str[8:12]}-{uuid_str[12:16]}-{uuid_str[16:20]}-{uuid_str[20:]}"
        return uuid_str

    def _query_database(self, **kwargs):
        """Notion DB 쿼리 (raw request workaround via httpx)"""
        import httpx

        db_id = self._format_uuid(self.database_id)
        url = f"https://api.notion.com/v1/databases/{db_id}/query"

        # self.notion.options may not be available depending on version
        # Use simple auth header construction
        headers = {
            "Authorization": f"Bearer {self.notion.options.auth if hasattr(self.notion, 'options') else NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client() as client:
                resp = client.post(url, headers=headers, json=kwargs, timeout=30.0)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            log.error(f"HTTPX Query Failed: {e}")
            raise e

    def _build_page_index(self) -> Dict[str, Dict]:
        """DB의 모든 페이지를 NO 기준으로 인덱싱"""
        index = {}
        has_more = True
        start_cursor = None

        while has_more:
            kwargs = {
                "page_size": 100,
            }
            if start_cursor:
                kwargs["start_cursor"] = start_cursor

            try:
                response = self._query_database(**kwargs)
                for page in response["results"]:
                    no = self._extract_text(page["properties"].get("NO", {}))
                    if no:
                        index[no] = {
                            "page_id": page["id"],
                            "properties": page["properties"],
                            "last_edited": page.get("last_edited_time", ""),
                        }

                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")
            except Exception as e:
                log.error(f"DB 쿼리 중 오류 발생: {e}")
                has_more = False

        return index

    def _extract_text(self, prop: Dict) -> str:
        """Notion property에서 텍스트 추출"""
        ptype = prop.get("type", "")
        if ptype == "title":
            return prop["title"][0]["plain_text"] if prop.get("title") else ""
        elif ptype == "rich_text":
            return prop["rich_text"][0]["plain_text"] if prop.get("rich_text") else ""
        elif ptype == "select":
            return prop["select"]["name"] if prop.get("select") else ""
        elif ptype == "number":
            return str(prop.get("number", ""))
        elif ptype == "url":
            return prop.get("url", "") or ""
        elif ptype == "date":
            d = prop.get("date")
            return d["start"] if d else ""
        elif ptype == "email":
            return prop.get("email", "") or ""
        return ""

    def _build_notion_property(self, prop_name: str, value: str) -> Optional[Dict]:
        """값을 Notion property 형식으로 변환"""
        ptype = NOTION_PROP_TYPES.get(prop_name)
        if not ptype or not value:
            return None

        if ptype == "title":
            return {"title": [{"text": {"content": value[:2000]}}]}
        elif ptype == "rich_text":
            return {"rich_text": [{"text": {"content": value[:2000]}}]}
        elif ptype == "select":
            return {"select": {"name": value}}
        elif ptype == "date":
            # 날짜 형식 정규화
            clean = value.strip()
            if not clean:
                return None
            return {"date": {"start": clean}}
        elif ptype == "url":
            return {"url": value if value else None}
        elif ptype == "number":
            try:
                return {"number": float(value)}
            except ValueError:
                return None
        return None

    def sync_from_sheets(
        self,
        records: List[Dict[str, Any]],
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """Google Sheets → Notion 동기화"""
        log.info("Notion DB 페이지 인덱스 구축 중...")
        existing = self._build_page_index()
        log.info(f"기존 Notion 페이지: {len(existing)}개")

        stats = {"created": 0, "updated": 0, "unchanged": 0, "errors": 0}

        for record in records:
            issue_no = str(record.get("NO", "")).strip()
            title = str(record.get("이슈명", "")).strip()
            if not issue_no or not title:
                continue

            try:
                # Notion property 구성
                properties = {}
                for notion_prop, sheets_col in NOTION_TO_SHEETS_MAP.items():
                    val = str(record.get(sheets_col, "")).strip()
                    if not val:
                        continue
                    built = self._build_notion_property(notion_prop, val)
                    if built:
                        properties[notion_prop] = built

                if issue_no in existing:
                    # 기존 페이지 — 변경 확인 후 업데이트
                    page_info = existing[issue_no]
                    changes = self._detect_changes(page_info["properties"], properties)
                    if not changes:
                        stats["unchanged"] += 1
                        continue

                    if dry_run:
                        log.info(
                            f"  [DRY-RUN] 갱신: {issue_no} " f"({len(changes)}개 필드)"
                        )
                        stats["updated"] += 1
                        continue

                    self.notion.pages.update(
                        page_id=page_info["page_id"],
                        properties=properties,
                    )
                    stats["updated"] += 1
                    log.info(f"  🔄 갱신: {issue_no} - {title[:40]}")
                    time.sleep(0.35)  # Rate limit
                else:
                    # 신규 페이지 생성
                    if dry_run:
                        log.info(f"  [DRY-RUN] 생성: {issue_no} - {title[:40]}")
                        stats["created"] += 1
                        continue

                    self.notion.pages.create(
                        parent={"database_id": self.database_id},
                        properties=properties,
                    )
                    stats["created"] += 1
                    log.info(f"  ✅ 생성: {issue_no} - {title[:40]}")
                    time.sleep(0.35)

            except Exception as e:
                stats["errors"] += 1
                log.error(f"  ❌ {issue_no}: {e}")
                time.sleep(1)  # Back off on errors

        return stats

    def _detect_changes(
        self,
        existing_props: Dict,
        new_props: Dict,
    ) -> List[str]:
        """변경된 필드 목록 반환"""
        changes = []
        for prop_name, new_val in new_props.items():
            old_prop = existing_props.get(prop_name, {})
            old_text = self._extract_text(old_prop)
            # 신규 property의 값 추출
            new_text = self._extract_text_from_built(new_val)
            if old_text.strip() != new_text.strip():
                changes.append(prop_name)
        return changes

    def _extract_text_from_built(self, built: Dict) -> str:
        """빌드된 Notion property에서 텍스트 추출"""
        if "title" in built:
            return built["title"][0]["text"]["content"]
        elif "rich_text" in built:
            return built["rich_text"][0]["text"]["content"]
        elif "select" in built:
            return built["select"]["name"]
        elif "date" in built:
            return built["date"]["start"] if built["date"] else ""
        elif "url" in built:
            return built["url"] or ""
        elif "number" in built:
            return str(built["number"])
        return ""

    def fetch_all_pages(self) -> List[Dict[str, str]]:
        """Notion DB의 모든 페이지를 flat dict로 반환"""
        index = self._build_page_index()
        results = []
        for no, info in index.items():
            row = {"page_id": info["page_id"]}
            for prop_name, prop_val in info["properties"].items():
                row[prop_name] = self._extract_text(prop_val)
            results.append(row)
        return results

    def get_notion_page_url(self, page_id: str) -> str:
        """페이지 ID → Notion URL"""
        clean = page_id.replace("-", "")
        return f"https://www.notion.so/{clean}"


# ─── Google Sheets Client (재사용) ──────────────────────────
def get_sheets_client():
    """Google Sheets 클라이언트 반환"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        log.error("gspread 패키지 필요: pip install gspread google-auth")
        return None, None

    if not CREDENTIALS_PATH.exists():
        log.error(f"인증 파일 없음: {CREDENTIALS_PATH}")
        return None, None

    config = load_config()
    ss_id = config.get("spreadsheet_id", "")
    sheet_name = config.get("sheet_name", "접수 메일")

    if not ss_id:
        log.error("spreadsheet_id 미설정")
        return None, None

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(
            str(CREDENTIALS_PATH), scopes=scopes
        )
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(ss_id)
        sheet = spreadsheet.worksheet(sheet_name)
        log.info(f"Google Sheets 연결 성공: " f"{spreadsheet.title} / {sheet_name}")
        return client, sheet
    except Exception as e:
        log.error(f"Google Sheets 연결 실패: {e}")
        return None, None


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


# ─── Commands ───────────────────────────────────────────────
def cmd_sync(args):
    """Google Sheets → Notion 동기화"""
    log.info("=" * 50)
    log.info("Google Sheets → Notion 동기화 시작")
    log.info("=" * 50)

    if not NOTION_API_KEY:
        log.error("NOTION_API_KEY가 .env에 설정되지 않았습니다")
        return
    if not NOTION_DATABASE_ID:
        log.error("NOTION_DATABASE_ID가 .env에 설정되지 않았습니다")
        return

    # Google Sheets 데이터 로드
    _, sheet = get_sheets_client()
    if not sheet:
        return

    try:
        records = sheet.get_all_records()
        log.info(f"Google Sheets에서 {len(records)}개 이슈 로드")
    except Exception as e:
        log.error(f"데이터 로드 실패: {e}")
        return

    # Notion 동기화
    notion = NotionSync(NOTION_API_KEY, NOTION_DATABASE_ID)
    dry_run = getattr(args, "dry_run", False)
    stats = notion.sync_from_sheets(records, dry_run=dry_run)

    log.info("")
    log.info("=" * 50)
    log.info("동기화 완료!")
    log.info(f"  생성: {stats['created']}개")
    log.info(f"  갱신: {stats['updated']}개")
    log.info(f"  변경없음: {stats['unchanged']}개")
    if stats["errors"]:
        log.warning(f"  오류: {stats['errors']}개")
    log.info("=" * 50)

    # Google Sheets에 NotionURL 업데이트 (생성된 페이지만)
    if not dry_run and stats["created"] > 0:
        _update_notion_urls(sheet, notion)


def _update_notion_urls(sheet, notion: NotionSync):
    """새로 생성된 Notion 페이지의 URL을 Sheets에 기록"""
    try:
        all_data = sheet.get_all_values()
        if not all_data:
            return

        headers = all_data[0]
        if "NotionURL" not in headers:
            log.info("NotionURL 컬럼이 없어 URL 업데이트 스킵")
            return

        notion_col = headers.index("NotionURL") + 1
        no_col = headers.index("NO") if "NO" in headers else 0

        # Notion에서 전체 페이지 인덱스 재구축
        pages = notion.fetch_all_pages()
        page_map = {p.get("NO", ""): p for p in pages}

        import gspread.utils

        batch = []
        for row_idx, row in enumerate(all_data[1:], start=2):
            if no_col >= len(row):
                continue
            issue_no = row[no_col]
            if not issue_no:
                continue

            # NotionURL이 비어있으면 채우기
            current_url = ""
            if notion_col - 1 < len(row):
                current_url = row[notion_col - 1].strip()

            if not current_url and issue_no in page_map:
                page_id = page_map[issue_no].get("page_id", "")
                if page_id:
                    url = notion.get_notion_page_url(page_id)
                    label = gspread.utils.rowcol_to_a1(row_idx, notion_col)
                    batch.append({"range": label, "values": [[url]]})

        if batch:
            sheet.batch_update(batch)
            log.info(f"NotionURL 업데이트: {len(batch)}건")
    except Exception as e:
        log.warning(f"NotionURL 업데이트 실패: {e}")


def cmd_push(args):
    """Notion → Google Sheets 역동기화"""
    log.info("=" * 50)
    log.info("Notion → Google Sheets 역동기화 시작")
    log.info("=" * 50)

    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        log.error("Notion API 설정이 .env에 없습니다")
        return

    notion = NotionSync(NOTION_API_KEY, NOTION_DATABASE_ID)
    dry_run = getattr(args, "dry_run", False)

    # Notion 데이터 가져오기
    pages = notion.fetch_all_pages()
    log.info(f"Notion에서 {len(pages)}개 페이지 로드")

    if not pages:
        log.info("역동기화할 데이터 없음")
        return

    # Google Sheets 연결
    _, sheet = get_sheets_client()
    if not sheet:
        return

    try:
        all_data = sheet.get_all_values()
        headers = all_data[0]
        no_col = headers.index("NO") if "NO" in headers else 0

        # Sheets 행 인덱스 맵
        row_map = {}
        for row_idx, row in enumerate(all_data[1:], start=2):
            if no_col < len(row) and row[no_col]:
                row_map[row[no_col]] = (row_idx, row)

        import gspread.utils

        batch = []
        update_count = 0
        skip_count = 0

        # 역동기화 대상: Notion에서 변경된 필드 → Sheets
        push_fields = ["상태", "담당자", "결정사항", "조치계획"]

        for page in pages:
            issue_no = page.get("NO", "").strip()
            if not issue_no or issue_no not in row_map:
                continue

            target_row, current_row = row_map[issue_no]

            for notion_prop in push_fields:
                sheets_col = NOTION_TO_SHEETS_MAP.get(notion_prop, notion_prop)
                if sheets_col not in headers:
                    continue

                notion_val = page.get(notion_prop, "").strip()
                if not notion_val:
                    continue

                col_idx = headers.index(sheets_col) + 1
                current_val = ""
                if col_idx - 1 < len(current_row):
                    current_val = current_row[col_idx - 1].strip()

                # Sheets에 이미 값이 있으면 스킵
                if current_val:
                    skip_count += 1
                    continue

                if dry_run:
                    log.info(
                        f"  [DRY-RUN] {issue_no}." f"{sheets_col} = {notion_val[:30]}"
                    )
                else:
                    label = gspread.utils.rowcol_to_a1(target_row, col_idx)
                    batch.append({"range": label, "values": [[notion_val]]})

                update_count += 1

        if not dry_run and batch:
            sheet.batch_update(batch)

        log.info("")
        log.info("=" * 50)
        log.info(f"역동기화 완료: {update_count}건 반영")
        log.info(f"  스킵 (기존값): {skip_count}건")
        log.info("=" * 50)

    except Exception as e:
        log.error(f"역동기화 실패: {e}")


def cmd_status(args):
    """동기화 상태 확인"""
    print("=" * 50)
    print("P5 Notion ↔ Google Sheets 동기화 상태")
    print("=" * 50)

    # Notion 상태
    if NOTION_API_KEY and NOTION_DATABASE_ID:
        try:
            notion = NotionSync(NOTION_API_KEY, NOTION_DATABASE_ID)
            pages = notion.fetch_all_pages()
            print(f"\n📋 Notion 페이지: {len(pages)}개")

            # 상태별 집계
            status_count: Dict[str, int] = {}
            for p in pages:
                s = p.get("상태", "미지정") or "미지정"
                status_count[s] = status_count.get(s, 0) + 1
            print("   상태별:")
            for s, c in sorted(status_count.items(), key=lambda x: -x[1]):
                print(f"     {s}: {c}개")
        except Exception as e:
            print(f"\n❌ Notion 연결 실패: {e}")
    else:
        print("\n⚠️ Notion API 미설정")

    # Google Sheets 상태
    _, sheet = get_sheets_client()
    if sheet:
        try:
            records = sheet.get_all_records()
            print(f"\n📊 Google Sheets 이슈: {len(records)}개")
        except Exception as e:
            print(f"\n❌ Sheets 로드 실패: {e}")

    # 로그 마지막 수정
    if LOG_FILE.exists():
        mtime = datetime.fromtimestamp(os.path.getmtime(LOG_FILE))
        print(f"\n🕐 마지막 동기화: " f"{mtime.strftime('%Y-%m-%d %H:%M:%S')}")


# ─── Main ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="P5 Notion ↔ Google Sheets 동기화",
    )
    sub = parser.add_subparsers(dest="command", help="명령어")

    # sync
    p_sync = sub.add_parser("sync", help="Google Sheets → Notion 동기화")
    p_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="변경 없이 미리보기",
    )
    p_sync.set_defaults(func=cmd_sync)

    # push
    p_push = sub.add_parser("push", help="Notion → Google Sheets 역동기화")
    p_push.add_argument(
        "--dry-run",
        action="store_true",
        help="변경 없이 미리보기",
    )
    p_push.set_defaults(func=cmd_push)

    # status
    p_status = sub.add_parser("status", help="동기화 상태 확인")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
