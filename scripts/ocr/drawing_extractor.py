"""
Drawing Extractor — 도면번호 자동 추출

건설 프로젝트 도면에서 도면번호, 리비전, 참조 도면을 추출.
GLM-OCR 구조화 프롬프트 + 정규식 후처리 조합.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Set, TYPE_CHECKING

from .glm_ocr_client import GlmOcrClient, OcrResult

if TYPE_CHECKING:
    from .correction_manager import CorrectionManager

log = logging.getLogger(__name__)

# ─── P5 프로젝트 도면번호 패턴 ──────────────────────────────────
DRAWING_PATTERNS = [
    # 일반 이슈 코드: SEN-070, EP-001
    re.compile(r"\b([A-Z]{2,4}-\d{3,})\b"),
    # 구조 도면: S-001, S-1234
    re.compile(r"\b(S-\d{3,})\b"),
    # SHOP 도면: SHOP-R01, SHOP_Rev2
    re.compile(r"\b(SHOP[-_]R(?:ev)?\d+)\b", re.IGNORECASE),
    # Embedded Plate: EP-01, EP-105
    re.compile(r"\b(EP[-_]\d{2,})\b"),
    # PSRC 기둥: PSRC-01, PSRC_32
    re.compile(r"\b(PSRC[-_]\d{2,})\b"),
    # HMB: HMB-01, HMB_15
    re.compile(r"\b(HMB[-_]\d{2,})\b"),
    # PLEG / PLEB 특화 공법
    re.compile(r"\b(PLE[GB][-_]\d{2,})\b"),
    # FCC: FCC-001
    re.compile(r"\b(FCC[-_]\d{2,})\b"),
    # 일반 도면번호: DWG-001, DRW-001
    re.compile(r"\b(D[WR][GW][-_]\d{3,})\b", re.IGNORECASE),
]

# GLM-OCR 도면번호 추출용 프롬프트
DRAWING_EXTRACT_PROMPT = """건설 도면 문서를 분석합니다. 이미지에서 모든 도면번호, 리비전 번호, 문서 ID를 추출하세요.

확인 대상:
1. 타이틀 블록: 도면번호, 리비전, 날짜
2. 참조 도면 콜아웃 (Detail, Section 마커)
3. 디테일 마커의 도면 참조
4. 부재 기호 (EP, PSRC, HMB, PLEG, FCC 등)

JSON 형식으로 반환:
{"drawing_numbers": [...], "revision": "...", "date": "...", "title": "...", "referenced_drawings": [...]}"""


@dataclass
class DrawingInfo:
    """추출된 도면 정보."""
    drawing_numbers: List[str] = field(default_factory=list)
    revision: str = ""
    date: str = ""
    title: str = ""
    referenced_drawings: List[str] = field(default_factory=list)
    source_file: str = ""
    page_number: int = 0
    confidence: float = 0.0
    source: str = ""  # "structured" | "regex" | "none"
    per_drawing_confidence: Dict[str, float] = field(default_factory=dict)


class DrawingExtractor:
    """도면번호 추출기.

    두 가지 방식 조합:
    1. GLM-OCR 구조화 프롬프트 → JSON 파싱
    2. OCR 텍스트에서 정규식 추출 (폴백 + 보완)
    """

    def __init__(
        self,
        ocr_client: GlmOcrClient,
        correction_manager: Optional["CorrectionManager"] = None,
    ):
        self.ocr_client = ocr_client
        self.correction_manager = correction_manager

    def extract_from_image(self, image_path: Path) -> DrawingInfo:
        """이미지에서 도면번호 추출."""
        result = self.ocr_client.ocr_structured(
            image_path, prompt=DRAWING_EXTRACT_PROMPT,
        )
        return self._build_drawing_info(result, image_path)

    def extract_from_pdf(
        self, pdf_path: Path, max_pages: int = 10
    ) -> List[DrawingInfo]:
        """PDF에서 페이지별 도면번호 추출."""
        results = self.ocr_client.ocr_pdf_structured(
            pdf_path, prompt=DRAWING_EXTRACT_PROMPT, max_pages=max_pages,
        )
        return [
            self._build_drawing_info(r, pdf_path)
            for r in results
        ]

    def extract_from_text(self, text: str) -> Set[str]:
        """텍스트에서 정규식으로 도면번호 추출 (이메일 본문용)."""
        found = set()
        for pattern in DRAWING_PATTERNS:
            for match in pattern.finditer(text):
                found.add(match.group(1).upper())
        return found

    def extract_all_numbers(self, drawing_infos: List[DrawingInfo]) -> Set[str]:
        """DrawingInfo 리스트에서 모든 도면번호 수집 (중복 제거)."""
        all_nums = set()
        for info in drawing_infos:
            all_nums.update(info.drawing_numbers)
            all_nums.update(info.referenced_drawings)
        return all_nums

    # ─── 내부 메서드 ─────────────────────────────────────────────

    def _build_drawing_info(
        self, ocr_result: OcrResult, source_path: Path,
    ) -> DrawingInfo:
        """OcrResult → DrawingInfo 변환 (GLM-OCR JSON + 정규식 보완)."""
        info = DrawingInfo(
            source_file=str(source_path),
            page_number=ocr_result.page_number,
        )

        ocr_conf = ocr_result.confidence  # GlmOcrClient가 추정한 응답 품질

        # 1) GLM-OCR 구조화 데이터에서 추출
        sd = ocr_result.structured_data
        extraction_conf = 0.3  # 기본: 미발견
        if sd:
            info.drawing_numbers = [
                n.upper() for n in sd.get("drawing_numbers", [])
                if isinstance(n, str)
            ]
            info.referenced_drawings = [
                n.upper() for n in sd.get("referenced_drawings", [])
                if isinstance(n, str)
            ]
            info.revision = str(sd.get("revision", ""))
            info.date = str(sd.get("date", ""))
            info.title = str(sd.get("title", ""))
            extraction_conf = 0.9
            info.source = "structured"
            # 구조화 추출 도면번호 → 높은 개별 확신도
            for num in info.drawing_numbers:
                info.per_drawing_confidence[num] = 0.9

        # 2) 정규식으로 추가 도면번호 추출 (보완)
        regex_nums = self.extract_from_text(ocr_result.raw_text)
        existing = set(info.drawing_numbers) | set(info.referenced_drawings)
        new_from_regex = regex_nums - existing

        if new_from_regex:
            info.drawing_numbers.extend(sorted(new_from_regex))
            # regex 추출은 낮은 개별 확신도
            for num in new_from_regex:
                info.per_drawing_confidence[num] = 0.7
            log.debug(
                "정규식 보완: %d개 추가 → %s",
                len(new_from_regex), new_from_regex,
            )

        # 3) 확신도: 추출 방식 + OCR 응답 품질 가중 평균
        #    - EXTRACTION_WEIGHT (0.6): 추출 방식 신뢰도 — structured(0.9) > regex(0.7) > none(0.3)
        #    - OCR_WEIGHT (0.4): GLM-OCR 응답 품질 점수 (응답 길이/구조 기반 휴리스틱)
        #    근거: 추출 방식이 OCR 품질보다 결과 정확도에 더 큰 영향을 미침
        EXTRACTION_WEIGHT = 0.6
        OCR_WEIGHT = 0.4

        if not sd and info.drawing_numbers:
            extraction_conf = 0.7  # 정규식만
            info.source = "regex"
        elif not info.drawing_numbers:
            extraction_conf = 0.3
            info.source = "none"

        info.confidence = round(
            (extraction_conf * EXTRACTION_WEIGHT) + (ocr_conf * OCR_WEIGHT), 2
        )

        # 4) 교정 적용 (별칭 맵)
        if self.correction_manager:
            info = self.correction_manager.apply_to_drawing_info(info)

        return info
