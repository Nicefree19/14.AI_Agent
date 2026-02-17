"""
P5 OCR Module — GLM-OCR via Ollama 기반 첨부파일 자동 인식

하위 모듈:
- glm_ocr_client: Ollama GLM-OCR 클라이언트
- drawing_extractor: 도면번호 정규식 추출
- table_extractor: 표 구조 추출
- attachment_processor: 첨부파일 자동 처리
- image_preprocessor: Pillow 기반 이미지 전처리
- correction_manager: OCR 결과 교정
- drawing_preprocessor: OpenCV 고급 도면 전처리
- zone_detector: 도면 영역 자동 분할
- structural_analyzer: Zone 기반 다중 프롬프트 구조 분석
- dxf_parser: DXF/DWG 직접 파싱
- report_generator: 분석 결과 리포트 생성
"""

from .glm_ocr_client import GlmOcrClient, OcrResult
from .drawing_extractor import DrawingExtractor
from .table_extractor import TableExtractor, ExtractedTable
from .attachment_processor import AttachmentProcessor, AttachmentResult
from .image_preprocessor import ImagePreprocessor, PreprocessConfig
from .correction_manager import CorrectionManager

# ── 정밀 도면 분석 모듈 ──
from .drawing_preprocessor import DrawingPreprocessor, DrawingPreprocessConfig
from .zone_detector import ZoneDetector, DrawingZone
from .structural_analyzer import StructuralAnalyzer
from .dxf_parser import DxfParser, DxfAnalysis
from .report_generator import DrawingReportGenerator

__all__ = [
    # 기존 모듈
    "GlmOcrClient",
    "OcrResult",
    "DrawingExtractor",
    "TableExtractor",
    "ExtractedTable",
    "AttachmentProcessor",
    "AttachmentResult",
    "ImagePreprocessor",
    "PreprocessConfig",
    "CorrectionManager",
    # 정밀 도면 분석
    "DrawingPreprocessor",
    "DrawingPreprocessConfig",
    "ZoneDetector",
    "DrawingZone",
    "StructuralAnalyzer",
    "DxfParser",
    "DxfAnalysis",
    "DrawingReportGenerator",
]
