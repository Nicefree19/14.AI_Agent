"""
Zone Detector — 건설 도면 영역 자동 분할

도면을 의미있는 영역(Zone)으로 분할하여 각 영역에 전문화된 OCR 프롬프트 적용.
OpenCV Hough 변환, Contour 분석, 비율 기반 감지.

Zone 타입:
- title_block: 우하단 타이틀 블록 (도면번호, 리비전, 스케일)
- main_drawing: 주 도면 영역 (구조 상세, 배근도)
- notes: 일반 주석/범례 영역
- schedule: 테이블/일정표 영역
- detail: 상세도 (원형 마커 내부)
- section_mark: 단면 마커
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class DrawingZone:
    """감지된 도면 영역."""
    zone_type: str                     # Zone 타입
    bbox: Tuple[int, int, int, int]    # (x, y, w, h)
    image: np.ndarray = field(repr=False)  # 크롭된 이미지
    confidence: float = 0.0
    label: str = ""                    # 추가 라벨 (예: "Detail A")

    @property
    def area(self) -> int:
        return self.bbox[2] * self.bbox[3]

    @property
    def center(self) -> Tuple[int, int]:
        x, y, w, h = self.bbox
        return (x + w // 2, y + h // 2)


class ZoneDetector:
    """도면 영역 자동 분할.

    건설 구조 도면의 일반적 레이아웃:
    ┌─────────────────────────────────┐
    │                                 │
    │        Main Drawing             │
    │     (구조 상세, 배근도)           │
    │                                 │
    │   ┌──────┐                      │
    │   │Detail│                      │
    │   │  A   │                      │
    │   └──────┘                      │
    │                                 │
    ├──────────┬──────────────────────┤
    │  Notes   │    Title Block       │
    │ (주석)    │  (도면번호/리비전)    │
    └──────────┴──────────────────────┘
    """

    ZONE_TYPES = [
        "title_block",
        "main_drawing",
        "notes",
        "schedule",
        "detail",
        "section_mark",
    ]

    # 타이틀 블록 위치 비율 (우하단)
    TITLE_BLOCK_X_RATIO = 0.55   # 우측 55% 지점부터
    TITLE_BLOCK_Y_RATIO = 0.80   # 하단 80% 지점부터
    TITLE_BLOCK_MIN_W_RATIO = 0.2  # 최소 너비 20%
    TITLE_BLOCK_MIN_H_RATIO = 0.08  # 최소 높이 8%

    # 상세도 마커 최소/최대 반경 (이미지 크기 대비)
    DETAIL_MIN_R_RATIO = 0.03
    DETAIL_MAX_R_RATIO = 0.20

    def detect_zones(
        self,
        image: np.ndarray,
        detect_details: bool = True,
    ) -> List[DrawingZone]:
        """전체 도면에서 영역 자동 감지.

        Args:
            image: 전처리된 Grayscale 이미지
            detect_details: 상세도 원형 마커 감지 여부

        Returns:
            감지된 DrawingZone 목록 (zone_type별)
        """
        h, w = image.shape[:2]
        zones: List[DrawingZone] = []

        # Grayscale 보장
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # 1. 타이틀 블록 감지
        title_zone = self._detect_title_block(gray, w, h)
        if title_zone:
            zones.append(title_zone)
            log.info("타이틀 블록 감지: bbox=%s, conf=%.2f", title_zone.bbox, title_zone.confidence)

        # 2. 상세도 원형 마커 감지
        if detect_details:
            detail_zones = self._detect_detail_views(gray, w, h)
            zones.extend(detail_zones)
            if detail_zones:
                log.info("상세도 %d개 감지", len(detail_zones))

        # 3. 주석 영역 감지 (텍스트 밀집)
        notes_zone = self._detect_notes_area(gray, w, h, title_zone)
        if notes_zone:
            zones.append(notes_zone)

        # 4. 주 도면 영역 (나머지)
        main_zone = self._detect_main_drawing(gray, w, h, zones)
        zones.append(main_zone)

        return zones

    def _detect_title_block(
        self,
        gray: np.ndarray,
        w: int,
        h: int,
    ) -> Optional[DrawingZone]:
        """우하단 타이틀 블록 감지.

        건설 도면의 타이틀 블록은 일반적으로 우하단에 위치.
        Hough 라인 감지 + 비율 기반 후보 영역 검증.
        """
        try:
            # 후보 영역: 우하단
            x_start = int(w * self.TITLE_BLOCK_X_RATIO)
            y_start = int(h * self.TITLE_BLOCK_Y_RATIO)
            roi = gray[y_start:h, x_start:w]

            if roi.size == 0:
                return None

            # 에지 검출
            edges = cv2.Canny(roi, 50, 150)

            # 수평/수직 선 감지
            lines = cv2.HoughLinesP(
                edges,
                rho=1,
                theta=np.pi / 180,
                threshold=50,
                minLineLength=roi.shape[1] // 4,
                maxLineGap=5,
            )

            if lines is not None and len(lines) >= 3:
                # 선이 충분하면 타이틀 블록으로 판단
                confidence = min(0.95, 0.5 + len(lines) * 0.05)
            else:
                # 선이 부족해도 위치 기반으로 비율 영역 반환
                confidence = 0.6

            # 타이틀 블록 크기 검증
            tb_w = w - x_start
            tb_h = h - y_start

            if tb_w < w * self.TITLE_BLOCK_MIN_W_RATIO:
                return None
            if tb_h < h * self.TITLE_BLOCK_MIN_H_RATIO:
                return None

            cropped = gray[y_start:h, x_start:w].copy()
            return DrawingZone(
                zone_type="title_block",
                bbox=(x_start, y_start, tb_w, tb_h),
                image=cropped,
                confidence=confidence,
                label="Title Block",
            )

        except Exception as e:
            log.warning("타이틀 블록 감지 실패: %s", e)
            return None

    def _detect_notes_area(
        self,
        gray: np.ndarray,
        w: int,
        h: int,
        title_zone: Optional[DrawingZone],
    ) -> Optional[DrawingZone]:
        """텍스트 밀집 영역 감지 (좌하단 또는 우측).

        건설 도면에서 일반 노트/범례는 주로 하단 좌측에 위치.
        """
        try:
            # 하단 영역 (타이틀 블록 옆)
            y_start = int(h * 0.75)

            if title_zone:
                # 타이틀 블록 왼쪽
                x_end = title_zone.bbox[0]
            else:
                x_end = int(w * 0.55)

            if x_end < w * 0.15:
                return None  # 너무 좁으면 건너뜀

            roi = gray[y_start:h, 0:x_end]
            if roi.size == 0:
                return None

            # 텍스트 밀도 분석: 에지 밀도로 판단
            edges = cv2.Canny(roi, 50, 150)
            edge_density = np.sum(edges > 0) / edges.size

            if edge_density < 0.02:
                return None  # 거의 비어있음

            confidence = min(0.85, 0.4 + edge_density * 5)

            cropped = gray[y_start:h, 0:x_end].copy()
            return DrawingZone(
                zone_type="notes",
                bbox=(0, y_start, x_end, h - y_start),
                image=cropped,
                confidence=confidence,
                label="General Notes",
            )

        except Exception as e:
            log.warning("주석 영역 감지 실패: %s", e)
            return None

    def _detect_detail_views(
        self,
        gray: np.ndarray,
        w: int,
        h: int,
    ) -> List[DrawingZone]:
        """원형 상세도 마커 감지 (Hough Circle).

        건설 도면에서 상세도는 원형 마커로 표시됨.
        """
        detail_zones: List[DrawingZone] = []

        try:
            min_r = int(min(w, h) * self.DETAIL_MIN_R_RATIO)
            max_r = int(min(w, h) * self.DETAIL_MAX_R_RATIO)

            if min_r < 10:
                min_r = 10

            # 블러 적용 후 원형 감지
            blurred = cv2.GaussianBlur(gray, (9, 9), 2)
            circles = cv2.HoughCircles(
                blurred,
                cv2.HOUGH_GRADIENT,
                dp=1.2,
                minDist=min_r * 3,
                param1=100,
                param2=40,
                minRadius=min_r,
                maxRadius=max_r,
            )

            if circles is None:
                return detail_zones

            circles = np.round(circles[0]).astype(int)

            for idx, (cx, cy, r) in enumerate(circles[:5]):  # 최대 5개
                # 원 내부 영역 크롭 (정사각형)
                x1 = max(0, cx - r)
                y1 = max(0, cy - r)
                x2 = min(w, cx + r)
                y2 = min(h, cy + r)

                cropped = gray[y1:y2, x1:x2].copy()
                if cropped.size == 0:
                    continue

                detail_zones.append(DrawingZone(
                    zone_type="detail",
                    bbox=(x1, y1, x2 - x1, y2 - y1),
                    image=cropped,
                    confidence=0.7,
                    label=f"Detail {idx + 1}",
                ))

        except Exception as e:
            log.warning("상세도 감지 실패: %s", e)

        return detail_zones

    def _detect_main_drawing(
        self,
        gray: np.ndarray,
        w: int,
        h: int,
        existing_zones: List[DrawingZone],
    ) -> DrawingZone:
        """주 도면 영역 = 다른 Zone을 제외한 나머지.

        타이틀 블록, 노트, 상세도를 제외한 중앙 영역.
        """
        # 기본: 상단 75~80% 영역
        y_end = int(h * 0.78)

        # 기존 Zone의 y_start 최소값 참고
        for zone in existing_zones:
            if zone.zone_type in ("title_block", "notes"):
                y_end = min(y_end, zone.bbox[1])

        # 주 도면: 상단 전체 영역
        margin = max(5, int(h * 0.02))
        x_start = margin
        y_start = margin
        x_end = w - margin

        cropped = gray[y_start:y_end, x_start:x_end].copy()

        return DrawingZone(
            zone_type="main_drawing",
            bbox=(x_start, y_start, x_end - x_start, y_end - y_start),
            image=cropped,
            confidence=0.9,
            label="Main Drawing",
        )

    # ─── 유틸리티 ──────────────────────────────────────────────

    @staticmethod
    def visualize_zones(
        image: np.ndarray,
        zones: List[DrawingZone],
    ) -> np.ndarray:
        """Zone 감지 결과를 시각화 (디버그용).

        각 Zone을 다른 색상의 사각형으로 표시.
        """
        if len(image.shape) == 2:
            vis = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            vis = image.copy()

        colors = {
            "title_block": (0, 255, 0),     # 초록
            "main_drawing": (255, 0, 0),    # 파랑
            "notes": (0, 255, 255),         # 노랑
            "schedule": (255, 255, 0),      # 시안
            "detail": (0, 0, 255),          # 빨강
            "section_mark": (255, 0, 255),  # 마젠타
        }

        for zone in zones:
            x, y, w, h = zone.bbox
            color = colors.get(zone.zone_type, (128, 128, 128))
            cv2.rectangle(vis, (x, y), (x + w, y + h), color, 2)

            label = f"{zone.zone_type} ({zone.confidence:.0%})"
            cv2.putText(
                vis, label, (x + 5, y + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
            )

        return vis
