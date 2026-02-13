"""
Table Extractor — 건설 문서 테이블 구조화 추출

GLM-OCR을 사용하여 건설 도면/시방서의 테이블을 마크다운으로 변환하고
테이블 유형(하중표, 자재목록, 공정표 등)을 자동 분류.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .glm_ocr_client import GlmOcrClient, OcrResult

log = logging.getLogger(__name__)

# ─── 테이블 유형 분류 키워드 ─────────────────────────────────────
TABLE_TYPE_KEYWORDS = {
    "spec_sheet": [
        "시방", "규격", "spec", "specification", "사양",
        "강도", "두께", "치수", "dimension",
    ],
    "load_table": [
        "하중", "활하중", "행잉", "로딩", "loading", "load",
        "kN", "kN/m", "kPa", "N/mm",
    ],
    "material_list": [
        "자재", "수량", "BOM", "물량", "부재", "material",
        "EA", "SET", "규격", "제원", "품명",
    ],
    "schedule": [
        "공정", "일정", "마일스톤", "schedule", "milestone",
        "착수", "완료", "납기", "준공",
    ],
    "rebar_schedule": [
        "배근", "철근", "rebar", "bar", "diameter",
        "D10", "D13", "D16", "D19", "D22", "D25",
    ],
}

# GLM-OCR 테이블 추출 프롬프트
TABLE_EXTRACT_PROMPT = """이 건설 문서에서 모든 테이블을 추출하세요.

각 테이블을 다음 형식으로 반환:
1. 마크다운 테이블 (정확한 행/열 구조 유지)
2. 테이블 유형: spec_sheet(시방서), load_table(하중표), material_list(자재목록), schedule(공정표), rebar_schedule(배근표)
3. 병합 셀이 있으면 적절히 처리

JSON 형식:
{"tables": [{"markdown": "| col1 | col2 |\\n|---|---|\\n| val1 | val2 |", "type": "spec_sheet", "headers": ["col1", "col2"], "row_count": 1}]}"""


@dataclass
class ExtractedTable:
    """추출된 테이블."""
    source_file: str
    page_number: int
    table_index: int          # 한 페이지에 여러 테이블 가능
    markdown_table: str       # 마크다운 형식 테이블
    headers: List[str] = field(default_factory=list)
    row_count: int = 0
    table_type: str = "unknown"  # spec_sheet | load_table | material_list | schedule | rebar_schedule | unknown
    confidence: float = 0.0


class TableExtractor:
    """건설 문서 테이블 추출기.

    GLM-OCR 구조화 프롬프트로 테이블 추출 + 자동 유형 분류.
    """

    def __init__(self, ocr_client: GlmOcrClient):
        self.ocr_client = ocr_client

    def extract_tables_from_image(self, image_path: Path) -> List[ExtractedTable]:
        """이미지에서 테이블 추출."""
        result = self.ocr_client.ocr_structured(
            image_path, prompt=TABLE_EXTRACT_PROMPT,
        )
        return self._parse_tables(result, image_path)

    def extract_tables_from_pdf(
        self, pdf_path: Path, max_pages: int = 10,
    ) -> List[ExtractedTable]:
        """PDF에서 페이지별 테이블 추출."""
        results = self.ocr_client.ocr_pdf_structured(
            pdf_path, prompt=TABLE_EXTRACT_PROMPT, max_pages=max_pages,
        )
        all_tables = []
        for r in results:
            all_tables.extend(self._parse_tables(r, pdf_path))
        return all_tables

    def classify_table(self, table: ExtractedTable) -> str:
        """테이블 유형 분류 (건설 도메인)."""
        text = (table.markdown_table + " ".join(table.headers)).lower()

        scores = {}
        for ttype, keywords in TABLE_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text)
            if score > 0:
                scores[ttype] = score

        if scores:
            best = max(scores, key=scores.get)
            return best
        return "unknown"

    # ─── 내부 메서드 ─────────────────────────────────────────────

    def _parse_tables(
        self, ocr_result: OcrResult, source_path: Path,
    ) -> List[ExtractedTable]:
        """OcrResult → ExtractedTable 리스트 변환."""
        tables = []
        sd = ocr_result.structured_data

        if sd and "tables" in sd:
            # GLM-OCR JSON 구조화 결과
            for idx, tdata in enumerate(sd["tables"]):
                if not isinstance(tdata, dict):
                    continue

                markdown = tdata.get("markdown", "")
                headers = tdata.get("headers", [])
                row_count = tdata.get("row_count", 0)
                ttype = tdata.get("type", "unknown")

                if not markdown:
                    continue

                # row_count 자동 계산 (JSON에 없을 때)
                if row_count == 0:
                    row_count = self._count_rows(markdown)

                # headers 자동 추출 (JSON에 없을 때)
                if not headers:
                    headers = self._extract_headers(markdown)

                table = ExtractedTable(
                    source_file=str(source_path),
                    page_number=ocr_result.page_number,
                    table_index=idx,
                    markdown_table=markdown,
                    headers=headers,
                    row_count=row_count,
                    table_type=ttype,
                    confidence=0.85,
                )

                # 유형 재분류 (GLM-OCR 결과가 unknown이면)
                if table.table_type == "unknown":
                    table.table_type = self.classify_table(table)

                tables.append(table)
        else:
            # 폴백: raw_text에서 마크다운 테이블 찾기
            md_tables = self._find_markdown_tables(ocr_result.raw_text)
            for idx, md in enumerate(md_tables):
                table = ExtractedTable(
                    source_file=str(source_path),
                    page_number=ocr_result.page_number,
                    table_index=idx,
                    markdown_table=md,
                    headers=self._extract_headers(md),
                    row_count=self._count_rows(md),
                    table_type="unknown",
                    confidence=0.6,
                )
                table.table_type = self.classify_table(table)
                tables.append(table)

        if tables:
            log.debug(
                "테이블 %d개 추출 (Page %d): %s",
                len(tables), ocr_result.page_number,
                [t.table_type for t in tables],
            )
        return tables

    @staticmethod
    def _count_rows(markdown: str) -> int:
        """마크다운 테이블의 데이터 행 수."""
        lines = [l.strip() for l in markdown.strip().split("\n") if l.strip()]
        # 헤더 + 구분선 제외
        data_lines = [
            l for l in lines
            if "|" in l and not re.match(r"^\|[\s\-:|]+\|$", l)
        ]
        return max(0, len(data_lines) - 1)  # 헤더 1줄 제외

    @staticmethod
    def _extract_headers(markdown: str) -> List[str]:
        """마크다운 테이블의 헤더 추출."""
        lines = [l.strip() for l in markdown.strip().split("\n") if l.strip()]
        if not lines:
            return []
        # 첫 번째 줄에서 헤더 추출
        first = lines[0]
        if "|" in first:
            cells = [c.strip() for c in first.split("|")]
            return [c for c in cells if c]
        return []

    @staticmethod
    def _find_markdown_tables(text: str) -> List[str]:
        """텍스트에서 마크다운 테이블 블록 찾기."""
        tables = []
        lines = text.split("\n")
        current_table = []
        in_table = False

        for line in lines:
            stripped = line.strip()
            if "|" in stripped and (
                re.match(r"^\|.*\|$", stripped)
                or re.match(r"^\|[\s\-:|]+\|$", stripped)
            ):
                in_table = True
                current_table.append(stripped)
            elif in_table:
                if current_table and len(current_table) >= 3:
                    tables.append("\n".join(current_table))
                current_table = []
                in_table = False

        # 마지막 테이블 처리
        if in_table and current_table and len(current_table) >= 3:
            tables.append("\n".join(current_table))

        return tables
