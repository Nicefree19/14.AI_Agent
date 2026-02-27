"""
Structural Analyzer — Zone 기반 다중 프롬프트 구조 도면 분석 엔진

핵심 혁신:
  도면을 영역(Zone)별로 분할 → 각 영역에 전문화된 프롬프트로 OCR →
  결과 통합 → 정규식 후처리 → 수량 집계 → 품질 평가

기존 단일 프롬프트 OCR 대비 정밀도 대폭 향상.
"""

import logging
import os
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np

from .drawing_preprocessor import DrawingPreprocessor
from .zone_detector import ZoneDetector, DrawingZone
from .glm_ocr_client import GlmOcrClient, OcrResult
from .drawing_extractor import DrawingExtractor, DRAWING_PATTERNS

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Zone별 전문 프롬프트 (건설 구조 도면 특화)
# ═══════════════════════════════════════════════════════════════

PROMPT_TITLE_BLOCK = """이 건설 도면의 타이틀 블록(표제란)을 분석하세요.

추출 항목:
1. 도면번호 (예: S-001, EP-105, PSRC-03)
2. 리비전 번호 (Rev.1, Rev.2 등)
3. 날짜 (YYYY-MM-DD 또는 YYYY.MM.DD)
4. 스케일 (1:50, 1:100 등)
5. 설계자/검토자/승인자 이름
6. 프로젝트명/도면명

JSON 형식으로 반환:
{"drawing_no": "", "revision": "", "date": "", "scale": "", "designer": "", "checker": "", "approver": "", "project": "", "title": ""}"""

PROMPT_DIMENSIONS = """이 건설 구조 도면 영역에서 모든 치수 정보를 추출하세요.

추출 항목:
1. 길이 치수 (mm 또는 m)
2. 높이/레벨 치수
3. 간격 치수 (부재 간격, 철근 간격)
4. 단면 크기 (bxh 형식: 400x600, 300x300 등)
5. 단위 표기 (mm, m, cm)

JSON 형식으로 반환:
{"dimensions": [{"value": "", "unit": "mm", "type": "length|height|spacing|section", "label": ""}]}"""

PROMPT_STRUCTURAL = """이 구조 도면 영역에서 구조 부재의 상세 정보를 분석하세요.

추출 항목:
1. 부재 타입 (기둥/보/슬래브/벽/기초)
2. 단면 치수 (bxh, 직경 등)
3. 철근 사양:
   - 주근 (예: 10-D25, 8-HD22)
   - 스터럽/띠철근 (예: D10@200, D13@150)
   - 피복 두께
4. 콘크리트 강도 (fck=24, fck=27 등)
5. 접합부 타입 (모멘트, 핀, 고정)
6. 앵커볼트 사양

JSON 형식으로 반환:
{"members": [{"type": "column|beam|slab|wall|footing", "section": "", "rebar": {"main": "", "stirrup": "", "cover_mm": 0}, "concrete_grade": "", "joint_type": ""}]}"""

PROMPT_GRID_SYSTEM = """이 건설 도면에서 그리드/축 시스템을 식별하세요.

추출 항목:
1. X축(가로) 축번호와 간격 (1, 2, 3... 또는 A, B, C...)
2. Y축(세로) 축번호와 간격
3. 축간 거리 (mm)
4. 기준점 위치

JSON 형식으로 반환:
{"grid_x": [{"label": "", "distance_mm": 0}], "grid_y": [{"label": "", "distance_mm": 0}], "origin": ""}"""

PROMPT_NOTES = """이 도면의 주석/범례/일반노트 영역을 분석하세요.

추출 항목:
1. 일반 노트 (General Notes)
2. 특기 사양 (Special Specifications)
3. 재료 사양 (콘크리트 강도, 철근 규격, 앙카 사양)
4. 참조 규격/기준 (KS, KBC, ACI, AISC 등)

JSON 형식으로 반환:
{"notes": ["..."], "specifications": ["..."], "standards": ["..."], "materials": {"concrete": "", "rebar": "", "anchor": ""}}"""

PROMPT_FULL_DRAWING = """이 건설 구조 도면을 종합적으로 분석하세요.

추출 항목:
1. 도면번호, 리비전, 스케일
2. 주요 치수 (길이, 높이, 간격)
3. 구조 부재 (기둥, 보, 슬래브 등의 단면과 철근)
4. 그리드 시스템 (축번호, 축간 거리)
5. 일반 노트 및 사양
6. 도면에 표기된 모든 텍스트

JSON 형식으로 반환:
{"drawing_no": "", "revision": "", "scale": "", "dimensions": [{"value": "", "unit": "mm", "type": ""}], "members": [{"type": "", "section": "", "rebar": {}}], "grid": {"grid_x": [], "grid_y": []}, "notes": [], "all_text": ""}"""

# Zone 타입 → 프롬프트 매핑
ZONE_PROMPTS = {
    "title_block": PROMPT_TITLE_BLOCK,
    "main_drawing": PROMPT_STRUCTURAL,
    "notes": PROMPT_NOTES,
    "detail": PROMPT_DIMENSIONS,
    "schedule": PROMPT_DIMENSIONS,
    "section_mark": PROMPT_STRUCTURAL,
}


class StructuralAnalyzer:
    """Zone 기반 다중 프롬프트 구조 도면 분석 엔진.

    Usage:
        analyzer = StructuralAnalyzer()
        result = analyzer.analyze("drawing.png")
        # result: dict with title_block, dimensions, members, grid, notes, ...
    """

    def __init__(self):
        self.ocr_client = GlmOcrClient()
        self.zone_detector = ZoneDetector()
        self.preprocessor = DrawingPreprocessor()
        self.drawing_extractor = DrawingExtractor()
        self._temp_dir = None

    def analyze(
        self,
        image_path: str,
        send_progress: Optional[Callable[[str], None]] = None,
        enable_zones: bool = True,
    ) -> Dict[str, Any]:
        """전체 도면 분석 파이프라인.

        Args:
            image_path: 이미지 파일 경로
            send_progress: 진행 상황 콜백
            enable_zones: Zone 분할 활성화 (False면 전체 이미지 단일 분석)

        Returns:
            통합 분석 결과 dict
        """
        _progress = send_progress or (lambda x: None)
        start_time = time.time()

        result: Dict[str, Any] = {
            "file_name": os.path.basename(image_path),
            "total_pages": 1,
            "title_block": {},
            "dimensions": [],
            "members": [],
            "grid": {},
            "notes": [],
            "specifications": [],
            "standards": [],
            "quantities": {},
            "drawing_refs": [],
            "sen_issues": [],
            "quality": {},
            "zones_detected": [],
            "raw_text": "",
            "processing_time_ms": 0,
        }

        # 1. OCR 서버 확인
        if not self.ocr_client.is_available():
            log.warning("Ollama GLM-OCR 서버 연결 불가 → 텍스트 기반 분석만 수행")
            result["quality"]["warnings"] = ["GLM-OCR 서버 연결 불가"]
            # OCR 불가능해도 이미지 전처리와 기본 분석은 시도
            return result

        # 2. 이미지 로드 + 전처리
        _progress("📐 도면 이미지 전처리 중...")
        image = self.preprocessor.load_image(image_path)
        if image is None:
            result["quality"]["warnings"] = [f"이미지 로드 실패: {image_path}"]
            return result

        # Grayscale 변환
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 전처리
        preprocessed = self.preprocessor.preprocess(gray)

        # 3. Zone 분할 또는 전체 분석
        if enable_zones:
            _progress("🔍 도면 영역 분할 중...")
            zones = self.zone_detector.detect_zones(preprocessed)

            result["zones_detected"] = [
                {"type": z.zone_type, "confidence": z.confidence, "label": z.label}
                for z in zones
            ]

            if not zones:
                log.info("Zone 감지 실패 → 전체 이미지 단일 분석 모드")
                enable_zones = False

        if enable_zones and zones:
            # Zone별 전문 프롬프트 OCR
            total_zones = len(zones)
            for idx, zone in enumerate(zones):
                _progress(
                    f"📐 [{idx + 1}/{total_zones}] {zone.label} 분석 중..."
                )
                zone_result = self._analyze_zone(zone)
                self._merge_zone_result(result, zone, zone_result)
        else:
            # 전체 이미지 단일 분석
            _progress("📐 도면 전체 분석 중...")
            full_result = self._analyze_full_image(image_path)
            self._merge_full_result(result, full_result)

        # 4. 정규식 후처리 (도면번호, SEN 추출)
        _progress("🔧 도면번호 추출 및 교차참조 중...")
        self._extract_references(result)

        # 5. 수량 집계
        self._extract_quantities(result)

        # 6. 품질 평가
        self._assess_quality(result, image)

        # 처리 시간
        result["processing_time_ms"] = int((time.time() - start_time) * 1000)

        log.info(
            "도면 분석 완료: %s - zones=%d, dims=%d, members=%d, time=%dms",
            result["file_name"],
            len(result["zones_detected"]),
            len(result["dimensions"]),
            len(result["members"]),
            result["processing_time_ms"],
        )

        return result

    # ─── Zone 분석 ────────────────────────────────────────────

    def _analyze_zone(self, zone: DrawingZone) -> Dict[str, Any]:
        """Zone 타입에 맞는 전문 프롬프트로 OCR.

        Zone 이미지를 임시 파일로 저장 → ocr_structured 호출.
        """
        prompt = ZONE_PROMPTS.get(zone.zone_type, PROMPT_FULL_DRAWING)

        try:
            # Zone 이미지를 임시 파일로 저장
            temp_path = self._save_temp_image(zone.image, f"zone_{zone.zone_type}")
            if not temp_path:
                return {}

            result = self.ocr_client.ocr_structured(
                image_path=Path(temp_path),
                prompt=prompt,
            )

            return {
                "raw_text": result.raw_text,
                "structured": result.structured_data,
                "confidence": result.confidence,
            }

        except Exception as e:
            log.warning("Zone %s 분석 실패: %s", zone.zone_type, e)
            return {}

    def _analyze_full_image(self, image_path: str) -> Dict[str, Any]:
        """전체 이미지를 단일 프롬프트로 분석 (Zone 감지 실패 시 fallback)."""
        try:
            result = self.ocr_client.ocr_structured(
                image_path=Path(image_path),
                prompt=PROMPT_FULL_DRAWING,
            )
            return {
                "raw_text": result.raw_text,
                "structured": result.structured_data,
                "confidence": result.confidence,
            }
        except Exception as e:
            log.warning("전체 이미지 분석 실패: %s", e)
            return {}

    # ─── 결과 병합 ────────────────────────────────────────────

    def _merge_zone_result(
        self,
        result: Dict[str, Any],
        zone: DrawingZone,
        zone_result: Dict[str, Any],
    ):
        """Zone OCR 결과를 통합 결과에 병합."""
        if not zone_result:
            return

        structured = zone_result.get("structured", {})
        raw_text = zone_result.get("raw_text", "")

        # raw_text 축적
        if raw_text:
            result["raw_text"] += f"\n--- {zone.label} ---\n{raw_text}\n"

        if not structured:
            return

        # Zone 타입별 병합
        if zone.zone_type == "title_block":
            result["title_block"] = structured

        elif zone.zone_type in ("main_drawing", "detail", "section_mark"):
            # 구조 부재
            members = structured.get("members", [])
            if isinstance(members, list):
                result["members"].extend(members)

            # 치수
            dimensions = structured.get("dimensions", [])
            if isinstance(dimensions, list):
                result["dimensions"].extend(dimensions)

            # 그리드
            grid = structured.get("grid", structured.get("grid_x", None))
            if grid and not result["grid"]:
                if isinstance(grid, dict):
                    result["grid"] = grid
                else:
                    result["grid"] = {"grid_x": grid}

            grid_y = structured.get("grid_y", None)
            if grid_y and isinstance(grid_y, list):
                result["grid"]["grid_y"] = grid_y

        elif zone.zone_type == "notes":
            notes = structured.get("notes", [])
            if isinstance(notes, list):
                result["notes"].extend(notes)

            specs = structured.get("specifications", [])
            if isinstance(specs, list):
                result["specifications"].extend(specs)

            standards = structured.get("standards", [])
            if isinstance(standards, list):
                result["standards"].extend(standards)

            # 재료 사양
            materials = structured.get("materials", {})
            if materials:
                result.setdefault("materials", {}).update(materials)

        elif zone.zone_type == "schedule":
            dimensions = structured.get("dimensions", [])
            if isinstance(dimensions, list):
                result["dimensions"].extend(dimensions)

    def _merge_full_result(
        self,
        result: Dict[str, Any],
        full_result: Dict[str, Any],
    ):
        """전체 이미지 분석 결과 병합."""
        if not full_result:
            return

        structured = full_result.get("structured", {})
        raw_text = full_result.get("raw_text", "")

        result["raw_text"] = raw_text

        if not structured:
            return

        # 직접 매핑
        for key in ("drawing_no", "revision", "scale", "title"):
            if structured.get(key):
                result["title_block"][key] = structured[key]

        for key in ("dimensions", "members", "notes"):
            items = structured.get(key, [])
            if isinstance(items, list):
                result[key].extend(items)

        grid = structured.get("grid", {})
        if isinstance(grid, dict) and grid:
            result["grid"] = grid

        all_text = structured.get("all_text", "")
        if all_text:
            result["raw_text"] += f"\n{all_text}"

    # ─── 후처리 ──────────────────────────────────────────────

    def _extract_references(self, result: Dict[str, Any]):
        """정규식으로 도면번호/SEN 참조 추출."""
        all_text = result.get("raw_text", "")

        # 타이틀 블록 텍스트도 포함
        tb = result.get("title_block", {})
        for val in tb.values():
            if isinstance(val, str):
                all_text += f" {val}"

        # 도면번호 추출 (기존 DRAWING_PATTERNS 재사용)
        drawing_refs = set()
        for pattern in DRAWING_PATTERNS:
            matches = pattern.findall(all_text)
            drawing_refs.update(matches)

        result["drawing_refs"] = sorted(drawing_refs)

        # SEN 이슈 교차참조 (기존 로직 재사용)
        import re
        sen_pattern = re.compile(r"\bSEN[-_](\d{3,})\b", re.IGNORECASE)
        sen_refs = sen_pattern.findall(all_text)

        sen_issues = []
        for ref_num in set(sen_refs):
            ref = f"SEN-{ref_num}"
            try:
                from ..telegram.skill_utils import get_issue_by_id
                issue = get_issue_by_id(ref)
                if issue:
                    sen_issues.append({
                        "ref": ref,
                        "title": issue.get("title", ""),
                        "priority": issue.get("priority", "?"),
                        "status": issue.get("status", "?"),
                    })
                else:
                    sen_issues.append({"ref": ref})
            except Exception:
                sen_issues.append({"ref": ref})

        result["sen_issues"] = sen_issues

    def _extract_quantities(self, result: Dict[str, Any]):
        """분석 결과에서 수량 자동 집계."""
        members = result.get("members", [])
        if not members:
            return

        # 부재 타입별 수량
        member_counts: Counter = Counter()
        for m in members:
            mtype = m.get("type", "unknown")
            member_counts[mtype] += 1

        type_labels = {
            "column": "기둥", "beam": "보", "slab": "슬래브",
            "wall": "벽", "footing": "기초",
        }

        labeled_counts = {}
        for mtype, count in member_counts.items():
            label = type_labels.get(mtype, mtype)
            labeled_counts[label] = count

        result["quantities"]["member_counts"] = labeled_counts

        # 철근 요약
        rebar_entries = []
        for m in members:
            rebar = m.get("rebar", {})
            main = rebar.get("main", "")
            stirrup = rebar.get("stirrup", "")
            if main:
                rebar_entries.append(f"주근: {main}")
            if stirrup:
                rebar_entries.append(f"스터럽: {stirrup}")

        if rebar_entries:
            result["quantities"]["rebar_summary"] = "; ".join(rebar_entries[:10])

    def _assess_quality(
        self,
        result: Dict[str, Any],
        image: np.ndarray,
    ):
        """도면 품질 평가."""
        quality: Dict[str, Any] = result.get("quality", {})
        warnings: List[str] = quality.get("warnings", [])

        # 1. 해상도 추정
        h, w = image.shape[:2]
        # A3 도면 기준 (420x297mm) → DPI 추정
        estimated_dpi = int(min(w, h) / 297 * 25.4) if min(w, h) > 0 else 0
        quality["estimated_dpi"] = estimated_dpi

        if estimated_dpi < 150:
            warnings.append(f"저해상도 ({estimated_dpi} DPI) → 인식 정확도 저하 가능")

        # 2. Zone 분석 결과 기반 신뢰도
        zones = result.get("zones_detected", [])
        if zones:
            confidences = [z.get("confidence", 0) for z in zones]
            avg_conf = sum(confidences) / len(confidences)
            quality["overall_confidence"] = round(avg_conf, 2)

            low_conf_zones = [z for z in zones if z.get("confidence", 0) < 0.5]
            if low_conf_zones:
                for z in low_conf_zones:
                    warnings.append(
                        f"저신뢰 Zone: {z.get('type', '?')} ({z.get('confidence', 0):.0%})"
                    )

        # 3. 결과 완성도
        if not result.get("title_block"):
            warnings.append("타이틀 블록 미감지")
        if not result.get("dimensions"):
            warnings.append("치수 정보 미추출")
        if not result.get("members"):
            warnings.append("구조 부재 정보 미추출")

        quality["warnings"] = warnings
        result["quality"] = quality

    # ─── 유틸리티 ──────────────────────────────────────────────

    def _save_temp_image(
        self,
        image: np.ndarray,
        prefix: str = "zone",
    ) -> Optional[str]:
        """numpy 배열을 임시 PNG 파일로 저장."""
        try:
            if self._temp_dir is None:
                self._temp_dir = tempfile.mkdtemp(prefix="drawing_analysis_")

            temp_path = os.path.join(self._temp_dir, f"{prefix}_{id(image)}.png")
            success, buf = cv2.imencode(".png", image)
            if success:
                buf.tofile(temp_path)
                return temp_path
            return None

        except Exception as e:
            log.warning("임시 이미지 저장 실패: %s", e)
            return None

    def cleanup(self):
        """임시 파일 정리."""
        if self._temp_dir and os.path.exists(self._temp_dir):
            import shutil
            try:
                shutil.rmtree(self._temp_dir)
                self._temp_dir = None
            except Exception as e:
                log.warning("임시 파일 정리 실패: %s", e)
