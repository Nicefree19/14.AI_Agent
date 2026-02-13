"""
Image Preprocessor — OCR 전 이미지 전처리 파이프라인

Pillow 기반: Grayscale → AutoContrast → Denoise → Sharpen
스캔 문서/도면의 OCR 정확도 향상을 위한 전처리.
"""

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageFilter, ImageOps

log = logging.getLogger(__name__)


@dataclass
class PreprocessConfig:
    """이미지 전처리 설정."""
    enabled: bool = False
    grayscale: bool = True
    autocontrast: bool = True
    autocontrast_cutoff: int = 1        # percent
    denoise: bool = True
    denoise_size: int = 3               # MedianFilter kernel (홀수)
    sharpen: bool = True
    sharpen_radius: float = 2.0         # UnsharpMask radius
    sharpen_percent: int = 150          # UnsharpMask percent
    sharpen_threshold: int = 3          # UnsharpMask threshold

    # 인식 가능한 config 키 목록
    _KNOWN_KEYS = frozenset({
        "enabled", "grayscale", "autocontrast", "autocontrast_cutoff",
        "denoise", "denoise_size", "sharpen", "sharpen_radius",
        "sharpen_percent", "sharpen_threshold",
    })

    @staticmethod
    def from_yaml(cfg_dict: dict) -> "PreprocessConfig":
        """YAML config dict → PreprocessConfig."""
        if not cfg_dict:
            return PreprocessConfig()
        # 미인식 키 경고
        unknown = set(cfg_dict.keys()) - PreprocessConfig._KNOWN_KEYS
        if unknown:
            log.warning("전처리 설정: 미인식 키 무시됨 → %s", unknown)
        return PreprocessConfig(
            enabled=cfg_dict.get("enabled", False),
            grayscale=cfg_dict.get("grayscale", True),
            autocontrast=cfg_dict.get("autocontrast", True),
            autocontrast_cutoff=cfg_dict.get("autocontrast_cutoff", 1),
            denoise=cfg_dict.get("denoise", True),
            denoise_size=cfg_dict.get("denoise_size", 3),
            sharpen=cfg_dict.get("sharpen", True),
            sharpen_radius=cfg_dict.get("sharpen_radius", 2.0),
            sharpen_percent=cfg_dict.get("sharpen_percent", 150),
            sharpen_threshold=cfg_dict.get("sharpen_threshold", 3),
        )


class ImagePreprocessor:
    """Pillow 기반 이미지 전처리 파이프라인.

    Usage:
        config = PreprocessConfig(enabled=True)
        preprocessor = ImagePreprocessor(config)
        processed_bytes = preprocessor.preprocess_bytes(raw_bytes)
    """

    def __init__(self, config: PreprocessConfig):
        self.config = config

    @property
    def is_enabled(self) -> bool:
        return self.config.enabled

    def preprocess_bytes(self, img_bytes: bytes) -> bytes:
        """이미지 바이트 전처리 → 처리된 PNG 바이트 반환.

        Args:
            img_bytes: 원본 이미지 바이트 (PNG, JPG 등)

        Returns:
            전처리된 PNG 바이트. 전처리 비활성화 시 원본 반환.
        """
        if not self.config.enabled:
            return img_bytes

        try:
            img = Image.open(BytesIO(img_bytes))
            img = self._apply_pipeline(img)

            buf = BytesIO()
            img.save(buf, format="PNG")
            result = buf.getvalue()
            log.debug(
                "전처리 완료: %d bytes → %d bytes",
                len(img_bytes), len(result),
            )
            return result
        except Exception as e:
            log.warning("전처리 실패, 원본 사용: %s", e)
            return img_bytes

    def preprocess_file(self, image_path: Path) -> bytes:
        """이미지 파일 전처리 → PNG 바이트 반환."""
        raw = image_path.read_bytes()
        return self.preprocess_bytes(raw)

    def _apply_pipeline(self, img: Image.Image) -> Image.Image:
        """전처리 파이프라인 적용."""
        # Step 1: Grayscale (스캔 문서는 그레이스케일이 OCR에 유리)
        if self.config.grayscale:
            img = img.convert("L")
            # 3채널로 복원 (모델이 RGB 입력 기대)
            img = img.convert("RGB")

        # Step 2: AutoContrast (대비 향상)
        if self.config.autocontrast:
            img = ImageOps.autocontrast(
                img, cutoff=self.config.autocontrast_cutoff,
            )

        # Step 3: Denoise (미디안 필터)
        if self.config.denoise:
            kernel = self.config.denoise_size
            # MedianFilter는 홀수 커널만 지원
            if kernel % 2 == 0:
                kernel += 1
            img = img.filter(ImageFilter.MedianFilter(size=kernel))

        # Step 4: Sharpen (언샤프 마스크)
        if self.config.sharpen:
            img = img.filter(ImageFilter.UnsharpMask(
                radius=self.config.sharpen_radius,
                percent=self.config.sharpen_percent,
                threshold=self.config.sharpen_threshold,
            ))

        return img
