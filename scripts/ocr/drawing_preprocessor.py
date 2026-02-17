"""
Drawing Preprocessor — OpenCV 기반 건설 도면 고급 전처리

기존 Pillow ImagePreprocessor를 보완하는 OpenCV 전처리 파이프라인:
- 기울기 보정 (deskew)
- 적응적 이진화 (adaptive threshold)
- 선 강조 (morphology)
- 잡음 제거
- 텍스트 영역 대비 강화 (CLAHE)

건설 구조 도면의 OCR 정밀도 향상을 위한 전처리.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class DrawingPreprocessConfig:
    """도면 전처리 설정."""
    mode: str = "auto"                # "auto", "scan", "cad", "photo"
    deskew: bool = True               # 기울기 보정
    adaptive_threshold: bool = True   # 적응적 이진화
    enhance_lines: bool = False       # 선 강조 (기본 비활성 - 도면에 따라)
    remove_noise: bool = True         # 잡음 제거
    enhance_text: bool = True         # 텍스트 영역 대비 강화
    target_dpi: int = 300             # 목표 DPI (리사이즈 기준)


class DrawingPreprocessor:
    """건설 도면 전용 OpenCV 고급 전처리."""

    def __init__(self, config: Optional[DrawingPreprocessConfig] = None):
        self.config = config or DrawingPreprocessConfig()

    def preprocess(
        self,
        image: np.ndarray,
        mode: Optional[str] = None,
    ) -> np.ndarray:
        """전체 전처리 파이프라인 실행.

        Args:
            image: OpenCV 이미지 (BGR or Grayscale)
            mode: 전처리 모드 오버라이드
                  "scan"  - 스캔 도면 (기울기 보정 + 이진화 + 잡음 제거)
                  "cad"   - CAD 출력 (선 강조 + 대비)
                  "photo" - 현장 사진 (CLAHE + 잡음 제거 + 이진화)
                  "auto"  - 자동 감지

        Returns:
            전처리된 이미지 (Grayscale)
        """
        effective_mode = mode or self.config.mode

        if effective_mode == "auto":
            effective_mode = self._detect_mode(image)
            log.info("전처리 모드 자동 감지: %s", effective_mode)

        # Grayscale 변환
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        result = gray

        if effective_mode == "scan":
            result = self._pipeline_scan(result)
        elif effective_mode == "cad":
            result = self._pipeline_cad(result)
        elif effective_mode == "photo":
            result = self._pipeline_photo(result)
        else:
            # 기본: 간단한 전처리
            result = self._pipeline_default(result)

        return result

    # ─── 모드별 파이프라인 ──────────────────────────────────────

    def _pipeline_scan(self, gray: np.ndarray) -> np.ndarray:
        """스캔 도면 파이프라인."""
        if self.config.deskew:
            gray = self.deskew(gray)
        if self.config.remove_noise:
            gray = self.remove_noise(gray)
        if self.config.enhance_text:
            gray = self.enhance_text_regions(gray)
        return gray

    def _pipeline_cad(self, gray: np.ndarray) -> np.ndarray:
        """CAD 출력 파이프라인."""
        if self.config.remove_noise:
            gray = self.remove_noise(gray, kernel_size=3)
        if self.config.enhance_text:
            gray = self.enhance_text_regions(gray)
        return gray

    def _pipeline_photo(self, gray: np.ndarray) -> np.ndarray:
        """현장 사진 파이프라인."""
        if self.config.deskew:
            gray = self.deskew(gray)
        gray = self.enhance_text_regions(gray)
        if self.config.remove_noise:
            gray = self.remove_noise(gray)
        if self.config.adaptive_threshold:
            gray = self.adaptive_threshold(gray)
        return gray

    def _pipeline_default(self, gray: np.ndarray) -> np.ndarray:
        """기본 파이프라인."""
        if self.config.remove_noise:
            gray = self.remove_noise(gray, kernel_size=3)
        if self.config.enhance_text:
            gray = self.enhance_text_regions(gray)
        return gray

    # ─── 개별 전처리 함수 ──────────────────────────────────────

    def deskew(self, image: np.ndarray) -> np.ndarray:
        """Hough 변환 기반 기울기 보정.

        도면의 수평/수직 선을 감지하여 기울기 각도를 계산하고 보정.
        """
        try:
            # 에지 검출
            edges = cv2.Canny(image, 50, 150, apertureSize=3)

            # Hough 변환으로 직선 검출
            lines = cv2.HoughLinesP(
                edges,
                rho=1,
                theta=np.pi / 180,
                threshold=100,
                minLineLength=image.shape[1] // 8,  # 이미지 너비의 1/8 이상
                maxLineGap=10,
            )

            if lines is None:
                return image

            # 수평선 각도 추출
            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                # 수평선에 가까운 선만 (±15도 이내)
                if abs(angle) < 15 or abs(angle - 180) < 15:
                    angles.append(angle)

            if not angles:
                return image

            # 중앙값 각도로 보정
            median_angle = np.median(angles)

            if abs(median_angle) < 0.1:
                return image  # 보정 불필요

            log.info("기울기 보정: %.2f도", median_angle)

            # 회전 보정
            h, w = image.shape[:2]
            center = (w // 2, h // 2)
            rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            rotated = cv2.warpAffine(
                image,
                rotation_matrix,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return rotated

        except Exception as e:
            log.warning("기울기 보정 실패: %s", e)
            return image

    def adaptive_threshold(self, image: np.ndarray) -> np.ndarray:
        """적응적 이진화.

        영역별 밝기 차이를 고려하여 이진화 (스캔 도면에 유효).
        """
        try:
            return cv2.adaptiveThreshold(
                image,
                maxValue=255,
                adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                thresholdType=cv2.THRESH_BINARY,
                blockSize=31,   # 블록 크기 (홀수)
                C=10,           # 상수 감산
            )
        except Exception as e:
            log.warning("적응적 이진화 실패: %s", e)
            return image

    def enhance_lines(self, image: np.ndarray) -> np.ndarray:
        """모폴로지 연산으로 도면 선 강조.

        얇은 선이 OCR에서 무시되지 않도록 두께 보강.
        """
        try:
            # 수평선 강조
            h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
            h_lines = cv2.morphologyEx(image, cv2.MORPH_CLOSE, h_kernel)

            # 수직선 강조
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15))
            v_lines = cv2.morphologyEx(image, cv2.MORPH_CLOSE, v_kernel)

            # 원본과 합성
            enhanced = cv2.min(image, cv2.min(h_lines, v_lines))
            return enhanced

        except Exception as e:
            log.warning("선 강조 실패: %s", e)
            return image

    def remove_noise(
        self,
        image: np.ndarray,
        kernel_size: int = 3,
    ) -> np.ndarray:
        """가우시안 블러 + 모폴로지 잡음 제거.

        미세 잡음을 제거하면서 텍스트와 선은 보존.
        """
        try:
            # 가우시안 블러 (경미하게)
            blurred = cv2.GaussianBlur(image, (kernel_size, kernel_size), 0)

            # 모폴로지 OPEN으로 미세 잡음 제거
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
            cleaned = cv2.morphologyEx(blurred, cv2.MORPH_OPEN, kernel)

            return cleaned

        except Exception as e:
            log.warning("잡음 제거 실패: %s", e)
            return image

    def enhance_text_regions(self, image: np.ndarray) -> np.ndarray:
        """CLAHE (Contrast Limited Adaptive Histogram Equalization).

        텍스트 영역의 대비를 적응적으로 강화.
        도면 전체에 균일하게 적용 (Zone 분할 전에 사용).
        """
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(image)
            return enhanced

        except Exception as e:
            log.warning("CLAHE 적용 실패: %s", e)
            return image

    # ─── 유틸리티 ──────────────────────────────────────────────

    def _detect_mode(self, image: np.ndarray) -> str:
        """이미지 특성으로 전처리 모드 자동 감지.

        Returns:
            "scan", "cad", or "photo"
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 히스토그램 분석
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        total_pixels = gray.shape[0] * gray.shape[1]

        # 이진 비율 (흑백 비율이 높으면 CAD 출력)
        dark_ratio = np.sum(hist[:50]) / total_pixels
        light_ratio = np.sum(hist[200:]) / total_pixels
        binary_ratio = dark_ratio + light_ratio

        # 분산 (낮으면 균일한 배경 = CAD, 높으면 스캔/사진)
        variance = np.var(gray)

        if binary_ratio > 0.85:
            return "cad"  # 대부분 흑백 → CAD 출력
        elif variance > 3000:
            return "photo"  # 높은 분산 → 사진
        else:
            return "scan"  # 나머지 → 스캔 도면

    @staticmethod
    def load_image(file_path: str) -> Optional[np.ndarray]:
        """파일 경로에서 이미지 로드.

        한글 경로 지원 (cv2.imread 대신 numpy 경유).
        """
        try:
            path = Path(file_path)
            if not path.exists():
                log.error("파일 없음: %s", file_path)
                return None

            # 한글 경로 지원
            buf = np.fromfile(str(path), dtype=np.uint8)
            image = cv2.imdecode(buf, cv2.IMREAD_COLOR)

            if image is None:
                log.error("이미지 디코딩 실패: %s", file_path)
                return None

            return image

        except Exception as e:
            log.error("이미지 로드 실패: %s - %s", file_path, e)
            return None

    @staticmethod
    def save_image(image: np.ndarray, file_path: str) -> bool:
        """이미지 저장 (한글 경로 지원)."""
        try:
            path = Path(file_path)
            ext = path.suffix.lower()
            success, buf = cv2.imencode(ext, image)
            if success:
                buf.tofile(str(path))
                return True
            return False
        except Exception as e:
            log.error("이미지 저장 실패: %s - %s", file_path, e)
            return False
