"""
Correction Manager — OCR 도면번호 교정 관리자

별칭 맵(alias map)을 통한 OCR 오인식 교정 + 학습 루프.
- EP-1O5 → EP-105 (O→0 OCR 오인식)
- PSRC_O1 → PSRC-01 (O→0 + _→- 정규화)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from .drawing_extractor import DrawingInfo

log = logging.getLogger(__name__)


class CorrectionManager:
    """OCR 도면번호 교정 관리자.

    - YAML 파일에서 별칭 맵 로드
    - DrawingInfo에 교정 적용 (확신도 0.95)
    - 대화형 교정 추가 + 파일 저장
    - 저확신도 도면번호 목록 조회
    """

    def __init__(self, corrections_path: Path):
        self.corrections_path = Path(corrections_path)
        self._aliases: Dict[str, str] = {}
        self._corrections_log: List[dict] = []
        self._load()

    def _load(self):
        """교정 파일 로드. 파일 없으면 빈 별칭으로 동작."""
        if not self.corrections_path.exists():
            log.debug("교정 파일 없음, 빈 별칭 사용: %s", self.corrections_path)
            return
        try:
            data = yaml.safe_load(
                self.corrections_path.read_text(encoding="utf-8"),
            ) or {}
            raw_aliases = data.get("aliases", {}) or {}
            # 키를 대문자로 정규화
            self._aliases = {
                k.upper(): v.upper() for k, v in raw_aliases.items()
            }
            self._corrections_log = data.get("corrections_log", []) or []
            log.debug("교정 별칭 %d건 로드", len(self._aliases))
        except Exception as e:
            log.warning("교정 파일 로드 실패: %s", e)

    def save(self):
        """교정 데이터를 YAML 파일로 저장."""
        # 저장 시에는 원본 대소문자 유지를 위해 그대로 저장
        data = {
            "aliases": self._aliases,
            "corrections_log": self._corrections_log,
        }
        self.corrections_path.parent.mkdir(parents=True, exist_ok=True)
        self.corrections_path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        log.info("교정 파일 저장: %s (%d건)", self.corrections_path, len(self._aliases))

    @property
    def aliases(self) -> Dict[str, str]:
        return dict(self._aliases)

    def apply_corrections(self, drawing_numbers: List[str]) -> List[str]:
        """별칭 맵 적용. 교정된 도면번호 리스트 반환."""
        if not self._aliases:
            return drawing_numbers
        corrected = []
        for num in drawing_numbers:
            upper = num.upper()
            if upper in self._aliases:
                corrected.append(self._aliases[upper])
            else:
                corrected.append(num)
        return corrected

    def apply_to_drawing_info(self, info: "DrawingInfo") -> "DrawingInfo":
        """DrawingInfo의 도면번호에 별칭 적용 + 확신도 0.95 설정."""
        if not self._aliases:
            return info

        corrected_nums = []
        for num in info.drawing_numbers:
            upper = num.upper()
            if upper in self._aliases:
                corrected = self._aliases[upper]
                corrected_nums.append(corrected)
                info.per_drawing_confidence[corrected] = 0.95
                # 원본 키 제거
                info.per_drawing_confidence.pop(num, None)
                info.per_drawing_confidence.pop(upper, None)
                log.debug("교정 적용: %s → %s", num, corrected)
            else:
                corrected_nums.append(num)
        info.drawing_numbers = corrected_nums

        corrected_refs = []
        for num in info.referenced_drawings:
            upper = num.upper()
            if upper in self._aliases:
                corrected_refs.append(self._aliases[upper])
            else:
                corrected_refs.append(num)
        info.referenced_drawings = corrected_refs

        return info

    def add_correction(self, original: str, corrected: str):
        """새 별칭 추가 + 이력 기록."""
        original_upper = original.upper()
        corrected_upper = corrected.upper()
        self._aliases[original_upper] = corrected_upper
        self._corrections_log.append({
            "original": original_upper,
            "corrected": corrected_upper,
            "added_at": datetime.now().isoformat(),
        })
        log.info("교정 추가: %s → %s", original_upper, corrected_upper)

    def get_low_confidence_items(
        self,
        sidecar_dir: Path,
        threshold: float = 0.6,
    ) -> List[dict]:
        """사이드카 파일에서 저확신도 도면번호 목록 조회.

        Returns:
            [{"number": "EP-1O5", "confidence": 0.4, "source": "regex", "file": "..."}]
        """
        items = []
        if not sidecar_dir.exists():
            return items

        for ocr_file in sidecar_dir.rglob("*.ocr.md"):
            try:
                text = ocr_file.read_text(encoding="utf-8")
                if not text.startswith("---"):
                    continue
                end = text.find("---", 3)
                if end <= 0:
                    continue
                fm = yaml.safe_load(text[3:end]) or {}
                for d in fm.get("drawing_numbers", []):
                    if isinstance(d, dict):
                        try:
                            conf = float(d.get("confidence", 0.5))
                        except (ValueError, TypeError):
                            conf = 0.5
                        if conf < threshold:
                            items.append({
                                "number": d.get("number", ""),
                                "confidence": conf,
                                "source": d.get("source", "unknown"),
                                "file": str(ocr_file),
                            })
            except Exception as e:
                log.debug("사이드카 파싱 실패 (%s): %s", ocr_file, e)

        # 확신도 오름차순 정렬
        items.sort(key=lambda x: x["confidence"])
        return items
